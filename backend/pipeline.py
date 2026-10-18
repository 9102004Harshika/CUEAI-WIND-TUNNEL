"""
CUE Wind Tunnel — Multi-Agent Pipeline

5 async agent coroutines for the "Launch SSO for Acme Corp" scenario.
Ordering is EXTERNALLY controlled — the whole point is that the harness
can delay, reorder, or feed mutated commitments.
"""

from __future__ import annotations

import asyncio
import time
import asyncio
from typing import List, Dict, Optional, Any, Callable, Tuple
from models import Commitment, AgentDef, ScenarioDef, Event, AgentAction, Mutation, MutationType, ScenarioDef
from llm_client import BaseLLMClient, StubLLMClient


# ---------------------------------------------------------------------------
# Commitment Store — shared state that agents read from / write to
# ---------------------------------------------------------------------------

class CommitmentStore:
    """
    In-memory store of commitments, keyed by normalized key.
    Supports versioning: every write to the same key increments version.
    """

    def __init__(self):
        self._store: Dict[str, List[Commitment]] = {}  # key → [versions]
        self._by_id: Dict[str, Commitment] = {}

    def put(self, commitment: Commitment) -> Commitment:
        """Store a commitment, auto-incrementing version for its key."""
        existing = self._store.get(commitment.key, [])
        if existing:
            latest = existing[-1]
            commitment.version = latest.version + 1
            commitment.supersedes = latest.id
        else:
            commitment.version = 1
        self._store.setdefault(commitment.key, []).append(commitment)
        self._by_id[commitment.id] = commitment
        return commitment

    def get_latest(self, key: str) -> Optional[Commitment]:
        """Get the latest non-revoked commitment for a key."""
        versions = self._store.get(key, [])
        for c in reversed(versions):
            if not c.revoked:
                return c
        return None

    def get_by_id(self, commitment_id: str) -> Optional[Commitment]:
        return self._by_id.get(commitment_id)

    def get_all(self, key: str) -> List[Commitment]:
        return list(self._store.get(key, []))

    def revoke(self, key: str) -> Optional[Commitment]:
        """Revoke the latest commitment for a key. Returns the revoked commitment."""
        latest = self.get_latest(key)
        if latest:
            latest.revoked = True
            latest.revoked_at = getattr(self, '_clock', 0.0)
        return latest

    def update_value(self, key: str, new_value: str) -> Optional[Commitment]:
        """Change the value of the latest commitment for a key (content flip)."""
        latest = self.get_latest(key)
        if latest:
            # Create a new version with the flipped value
            flipped = Commitment(
                agent_id=latest.agent_id,
                statement=f"{latest.agent_id} changed {key} to {new_value}",
                key=key,
                value=new_value,
                created_at=getattr(self, '_clock', 0.0),
            )
            return self.put(flipped)
        return None


from models import AgentDef

async def generic_agent_runner(
    agent_def: AgentDef,
    store: CommitmentStore,
    llm: BaseLLMClient,
    trace: List[Event],
) -> Optional[Event]:
    """Universal agent runner that interprets an AgentDef config."""
    read_ids = []
    read_versions = []
    context_parts = []
    
    # 1. Read dependencies
    for r_key in agent_def.reads:
        c = store.get_latest(r_key)
        if not c:
            # Action boundary execution block
            action = AgentAction(
                agent_id=agent_def.id,
                action_type=f"execution_blocked",
                reads=read_ids,
                reads_versions=read_versions,
                executed_at=getattr(store, '_clock', 0.0),
                payload={"reason": f"missing or revoked dependency '{r_key}'"},
                produced_commitment_id=None
            )
            trace.append(action)
            return action
            
        read_ids.append(c.id)
        read_versions.append(c.version)
        context_parts.append(f"{r_key}={c.value}")
        
    context = "; ".join(context_parts) if context_parts else "No dependencies."
    
    # 2. Get LLM Decision
    decision = await llm.generate_decision(agent_def, context)
    
    # 3. Emit Commitment (if agent writes state)
    commitment_id = None
    if agent_def.writes:
        commitment = Commitment(
            agent_id=agent_def.id,
            statement=f"{agent_def.name} decided {decision} for {agent_def.writes}",
            key=agent_def.writes,
            value=decision,
            created_at=getattr(store, '_clock', 0.0),
        )
        commitment = store.put(commitment)
        trace.append(commitment)
        commitment_id = commitment.id
        
    # 4. Record Action
    action = AgentAction(
        agent_id=agent_def.id,
        action_type=f"execute_{agent_def.id}",
        reads=read_ids,
        reads_versions=read_versions,
        executed_at=getattr(store, '_clock', 0.0),
        payload={"decision": decision},
        produced_commitment_id=commitment_id,
    )
    trace.append(action)
    
    return action


# ---------------------------------------------------------------------------
# Pipeline runner — ordering is externally controlled
# ---------------------------------------------------------------------------

class PipelineRunner:
    """
    Discrete Event Simulator for the agent pipeline.
    Agents run concurrently when dependencies are met.
    """

    def __init__(
        self,
        scenario: ScenarioDef,
        llm: Optional[BaseLLMClient] = None,
        order: Optional[List[str]] = None,
    ):
        self.scenario = scenario
        self.llm = llm or StubLLMClient()
        self.agents_map = {a.id: a for a in scenario.agents}
        # We can still use 'order' for initial priority / iteration
        self.order = order or [a.id for a in scenario.agents]
        self.store = CommitmentStore()
        self.trace: List[Event] = []
        
        self.pre_hooks: Dict[str, List[Callable]] = {}
        self.post_hooks: Dict[str, List[Callable]] = {}
        
        # Timing state
        self.virtual_clock: float = 0.0
        self.agent_delay: Dict[str, float] = {}

    def add_pre_hook(self, agent_id: str, hook: Callable):
        self.pre_hooks.setdefault(agent_id, []).append(hook)

    def add_post_hook(self, agent_id: str, hook: Callable):
        self.post_hooks.setdefault(agent_id, []).append(hook)

    def set_agent_delay(self, agent_id: str, delay: float):
        """Allows mutations to artificially delay an agent's execution time."""
        self.agent_delay[agent_id] = delay

    async def reset(self):
        self.store = CommitmentStore()
        self.trace = []
        self.pre_hooks = {}
        self.post_hooks = {}
    def check_execution_safety(self, agent_id: str, decision: str) -> Tuple[str, str, Optional[str]]:
        """
        Enforce deterministic execution safety gate at the action boundary.
        Decouples safety enforcement from LLM output.
        Returns: (effective_decision, action_type, blocked_reason)
        """
        effective_decision = decision
        action_type = f"execute_{agent_id}"
        blocked_reason = None

        if agent_id == "deployment":
            qa_comm = self.store.get_latest("qa_approval")
            impl_comm = self.store.get_latest("implemented_protocol")
            auth_comm = self.store.get_latest("auth_protocol")

            if not qa_comm or qa_comm.revoked or qa_comm.value != "approved":
                if decision == "deploy":
                    effective_decision = "hold"
                    action_type = "deploy_blocked"
                    blocked_reason = "Safety gate: deployment prohibited without valid approved QA decision"
            elif auth_comm and impl_comm and auth_comm.value != impl_comm.value:
                if decision == "deploy":
                    effective_decision = "hold"
                    action_type = "deploy_blocked"
                    blocked_reason = "Safety gate: deployment prohibited on mismatched auth vs implemented protocols"

        return effective_decision, action_type, blocked_reason

    async def run_cascade(self, targets: List[str]):
        """Inject additional agents into an already-finished pipeline and resume simulation."""
        import heapq
        events = []
        seq_num = 0
        failed_polls = 0
        
        pipeline_queue_count = {}
        for agent_id in targets:
            pipeline_queue_count[agent_id] = pipeline_queue_count.get(agent_id, 0) + 1
            heapq.heappush(events, (self.virtual_clock, seq_num, "TRY_START", agent_id, None))
            seq_num += 1
            
        completed_agents = {}
        started_agents = {}
        
        # Track pending writes in the cascade so downstream agents wait for
        # upstream targets to finish producing their replacement commitments
        pending_writes = set()
        for agent_id in targets:
            agent_def = self.agents_map.get(agent_id)
            if agent_def and agent_def.writes:
                pending_writes.add(agent_def.writes)

        # We also need an explicit AgentAction in the trace to mark the start of a cascade repair.
        # Test 3 mandates a clear indicator that history is preserved and appended to.
        repair_marker = AgentAction(
            agent_id="system", 
            action_type="cascade_repair", 
            reads=[], 
            reads_versions=[], 
            executed_at=self.virtual_clock,
            payload={"targets": targets}
        )
        self.trace.append(repair_marker)
        
        while events:
            current_time, _, e_type, agent_id, data = heapq.heappop(events)
            self.virtual_clock = current_time
            self.store._clock = current_time
            
            agent_def = self.agents_map.get(agent_id)
            if not agent_def:
                continue
                
            if e_type == "TRY_START":
                ready = True
                for read_key in agent_def.reads:
                    if read_key in pending_writes:
                        ready = False
                        break
                    c = self.store.get_latest(read_key)
                    if not c or c.revoked:
                        ready = False
                        break
                        
                if ready:
                    failed_polls = 0
                    if started_agents.get(agent_id, 0) < pipeline_queue_count.get(agent_id, 0):
                        started_agents[agent_id] = started_agents.get(agent_id, 0) + 1
                        heapq.heappush(events, (current_time, seq_num, "READ_AND_DECIDE", agent_id, None))
                        seq_num += 1
                else:
                    failed_polls += 1
                    if sum(started_agents.values()) == sum(completed_agents.values()) and failed_polls >= len(events) + 1:
                        if all(e[2] == "TRY_START" for e in events):
                            break
                    heapq.heappush(events, (current_time + 1.0, seq_num, "TRY_START", agent_id, None))
                    seq_num += 1
                    
            elif e_type == "READ_AND_DECIDE":
                read_ids = []
                read_versions = []
                context_parts = []
                for read_key in agent_def.reads:
                    c = self.store.get_latest(read_key)
                    if c:
                        read_ids.append(c.id)
                        read_versions.append(c.version)
                        context_parts.append(f"{c.key}={c.value}")
                        
                context = "; ".join(context_parts) if context_parts else "No dependencies."
                decision = await self.llm.generate_decision(agent_def, context)
                
                delay = self.agent_delay.get(agent_id, 1.0)
                heapq.heappush(events, (current_time + delay, seq_num, "WRITE_AND_FINISH", agent_id, {
                    "decision": decision,
                    "read_ids": read_ids,
                    "read_versions": read_versions
                }))
                seq_num += 1
                
            elif e_type == "WRITE_AND_FINISH":
                decision = data["decision"]
                read_ids = data["read_ids"]
                read_versions = data["read_versions"]
                
                # Enforce execution safety gate for deployment side-effect
                effective_decision = decision
                action_type = f"execute_{agent_id}"
                blocked_reason = None
                
                if agent_id == "deployment":
                    qa_comm = self.store.get_latest("qa_approval")
                    impl_comm = self.store.get_latest("implemented_protocol")
                    auth_comm = self.store.get_latest("auth_protocol")
                    
                    if not qa_comm or qa_comm.revoked or qa_comm.value != "approved":
                        if decision == "deploy":
                            effective_decision = "hold"
                            action_type = "deploy_blocked"
                            blocked_reason = "Safety gate: deployment prohibited without valid approved QA decision"
                    elif auth_comm and impl_comm and auth_comm.value != impl_comm.value:
                        if decision == "deploy":
                            effective_decision = "hold"
                            action_type = "deploy_blocked"
                            blocked_reason = "Safety gate: deployment prohibited on mismatched auth vs implemented protocols"

                commitment_id = None
                if agent_def.writes:
                    commitment = Commitment(
                        agent_id=agent_id,
                        statement=f"{agent_def.name} decided {effective_decision} for {agent_def.writes}",
                        key=agent_def.writes,
                        value=effective_decision,
                        created_at=current_time,
                    )
                    commitment = self.store.put(commitment)
                    self.trace.append(commitment)
                    commitment_id = commitment.id
                    pending_writes.discard(agent_def.writes)
                    
                action_payload = {"decision_result": effective_decision}
                if blocked_reason:
                    action_payload["blocked_reason"] = blocked_reason
                    
                action = AgentAction(
                    agent_id=agent_id,
                    action_type=action_type,
                    reads=read_ids,
                    reads_versions=read_versions,
                    executed_at=current_time,
                    payload=action_payload,
                    produced_commitment_id=commitment_id
                )
                self.trace.append(action)
                
                for hook in self.post_hooks.get(agent_id, []):
                    if asyncio.iscoroutinefunction(hook):
                        await hook(self.store, self.trace)
                    else:
                        hook(self.store, self.trace)
                        
                completed_agents[agent_id] = completed_agents.get(agent_id, 0) + 1
                failed_polls = 0

        return self.trace

    async def run(self) -> List[Event]:
        self.store = CommitmentStore()
        self.store._clock = 0.0
        self.trace = []
        
        # Event Queue: list of (time, sequence, type, agent_id, data)
        import heapq
        events = []
        seq_num = 0
        failed_polls = 0
        
        # Count how many times each agent appears in the initial order
        pipeline_queue_count = {}
        for agent_id in self.order:
            pipeline_queue_count[agent_id] = pipeline_queue_count.get(agent_id, 0) + 1
            heapq.heappush(events, (0.0, seq_num, "TRY_START", agent_id, None))
            seq_num += 1
            
        completed_agents = {}
        started_agents = {}
        
        while events:
            # Advance clock securely to next event time
            current_time, _, e_type, agent_id, data = heapq.heappop(events)
            self.virtual_clock = current_time
            self.store._clock = current_time
            
            agent_def = self.agents_map.get(agent_id)
            if not agent_def:
                continue
                
            if e_type == "TRY_START":
                # Check if all reads exist
                ready = True
                for read_key in agent_def.reads:
                    c = self.store.get_latest(read_key)
                    if not c or c.revoked:
                        ready = False
                        break
                        
                if ready:
                    failed_polls = 0
                    # For DUPLICATE mutation to work, we just allow the agent to start. 
                    # If it was duplicate queued, it will start twice.
                    # We track start counts to allow exactly as many starts as were queued.
                    if started_agents.get(agent_id, 0) < pipeline_queue_count.get(agent_id, 0):
                        started_agents[agent_id] = started_agents.get(agent_id, 0) + 1
                        heapq.heappush(events, (current_time, seq_num, "READ_AND_DECIDE", agent_id, None))
                        seq_num += 1
                else:
                    failed_polls += 1
                    # Deadlock detection
                    if sum(started_agents.values()) == sum(completed_agents.values()) and failed_polls >= len(events) + 1:
                        if all(e[2] == "TRY_START" for e in events):
                            # Emit execution_blocked for all remaining agents!
                            stalled = {e[3] for e in events}
                            stalled.add(agent_id)  # Add the currently evaluating agent!
                            for sa in stalled:
                                self.trace.append(AgentAction(
                                    agent_id=sa,
                                    action_type="execution_blocked",
                                    executed_at=current_time,
                                    payload={"reason": "dependencies permanently missing or revoked"}
                                ))
                            break
                    
                    # Retry this agent later
                    # Keep time identical but put at back of queue?
                    # No, we MUST advance time slightly to prevent infinite zero-time loops.
                    heapq.heappush(events, (current_time + 1.0, seq_num, "TRY_START", agent_id, None))
                    seq_num += 1
                    
            elif e_type == "READ_AND_DECIDE":
                for hook in self.pre_hooks.get(agent_id, []):
                    if asyncio.iscoroutinefunction(hook):
                        await hook(self.store, self.trace)
                    else:
                        hook(self.store, self.trace)
                        
                # Perform Read Phase immediately
                read_ids, read_versions, context_parts = [], [], []
                blocked = False
                
                for r_key in agent_def.reads:
                    c = self.store.get_latest(r_key)
                    if not c or c.revoked:
                        action = AgentAction(
                            agent_id=agent_def.id,
                            action_type=f"execution_blocked",
                            reads=read_ids,
                            reads_versions=read_versions,
                            executed_at=current_time,
                            payload={"reason": f"missing or revoked dependency '{r_key}'"},
                            produced_commitment_id=None
                        )
                        self.trace.append(action)
                        blocked = True
                        break
                    read_ids.append(c.id)
                    read_versions.append(c.version)
                    context_parts.append(f"{r_key}={c.value}")
                    
                if blocked:
                    completed_agents.add(agent_id)
                    continue
                    
                context = "; ".join(context_parts) if context_parts else "No dependencies."
                decision = await self.llm.generate_decision(agent_def, context)
                
                
                # Apply delays simulating think/execution time
                delay = self.agent_delay.get(agent_id, 1.0)
                heapq.heappush(events, (current_time + delay, seq_num, "WRITE_AND_FINISH", agent_id, {
                    "decision": decision,
                    "read_ids": read_ids,
                    "read_versions": read_versions
                }))
                seq_num += 1
                failed_polls = 0
                
            elif e_type == "WRITE_AND_FINISH":
                decision = data["decision"]
                read_ids = data["read_ids"]
                read_versions = data["read_versions"]
                
                # Enforce execution safety gate for deployment side-effect
                effective_decision = decision
                action_type = f"execute_{agent_def.id}"
                blocked_reason = None
                
                if agent_def.id == "deployment":
                    qa_comm = self.store.get_latest("qa_approval")
                    impl_comm = self.store.get_latest("implemented_protocol")
                    auth_comm = self.store.get_latest("auth_protocol")
                    
                    if not qa_comm or qa_comm.revoked or qa_comm.value != "approved":
                        if decision == "deploy":
                            effective_decision = "hold"
                            action_type = "deploy_blocked"
                            blocked_reason = "Safety gate: deployment prohibited without valid approved QA decision"
                    elif auth_comm and impl_comm and auth_comm.value != impl_comm.value:
                        if decision == "deploy":
                            effective_decision = "hold"
                            action_type = "deploy_blocked"
                            blocked_reason = "Safety gate: deployment prohibited on mismatched auth vs implemented protocols"

                commitment_id = None
                if agent_def.writes:
                    commitment = Commitment(
                        agent_id=agent_def.id,
                        statement=f"{agent_def.name} decided {effective_decision} for {agent_def.writes}",
                        key=agent_def.writes,
                        value=effective_decision,
                        created_at=current_time,
                    )
                    commitment = self.store.put(commitment)
                    self.trace.append(commitment)
                    commitment_id = commitment.id
                    
                action_payload = {"decision": effective_decision}
                if blocked_reason:
                    action_payload["blocked_reason"] = blocked_reason
                    
                action = AgentAction(
                    agent_id=agent_def.id,
                    action_type=action_type,
                    reads=read_ids,
                    reads_versions=read_versions,
                    executed_at=current_time,
                    payload=action_payload,
                    produced_commitment_id=commitment_id,
                )
                self.trace.append(action)
                
                for hook in self.post_hooks.get(agent_id, []):
                    if asyncio.iscoroutinefunction(hook):
                        await hook(self.store, self.trace)
                    else:
                        hook(self.store, self.trace)
                        
                completed_agents[agent_id] = completed_agents.get(agent_id, 0) + 1
                
                # A completion means state changed! Reset failed polls so waiting agents get a fresh cycle.
                failed_polls = 0

        return self.trace

    def reset(self):
        self.store = CommitmentStore()
        self.trace = []
        self.pre_hooks = {}
        self.post_hooks = {}
        self.virtual_clock = 0.0
        self.agent_delay = {}


def create_pipeline(
    scenario: ScenarioDef,
    llm: Optional[BaseLLMClient] = None,
    order: Optional[List[str]] = None,
) -> PipelineRunner:
    """Factory for creating a fresh pipeline runner."""
    return PipelineRunner(scenario=scenario, llm=llm, order=order)
