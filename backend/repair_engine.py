"""
CUE Wind Tunnel — Deterministic Repair Engine & Counterexample Store
Follows strict P0 rules:
1. Declines duplicate executions immediately (side effect already happened in history).
2. For stale reads, safely re-runs the stale reader and downstream dependencies.
3. Re-verifies ALL invariants against the post-repair trace.
4. Distinguishes Accepted vs Declined with honest, non-punitive wording.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import json
import os
from models import Mutation, MutationType, Event, InvariantResult
from pipeline import create_pipeline
from scenarios import SSO_SCENARIO
from invariants import check_all_invariants
from mutations import apply_mutation
from run_pipeline import serialize_trace

class Counterexample(BaseModel):
    id: str
    scenario_name: str
    description: str
    seed: int = 42
    mutations: List[Dict[str, Any]]
    expected_invariants: List[str]
    expected_verdict: str # "ACCEPTED" | "DECLINED"
    decline_reason: Optional[str] = None

class RepairVerdict(BaseModel):
    status: str # "ACCEPTED" | "DECLINED"
    reason: str
    rerun_agents: List[str] = Field(default_factory=list)
    side_effect_ledger: List[Dict[str, Any]] = Field(default_factory=list)
    residual_violations: List[str] = Field(default_factory=list)
    all_passed_after: bool = False
    trace_before_serialized: List[Dict[str, Any]] = Field(default_factory=list)
    trace_after_serialized: List[Dict[str, Any]] = Field(default_factory=list)

async def evaluate_repair(
    mutations: List[Mutation],
    scenario = SSO_SCENARIO,
    llm = None
) -> RepairVerdict:
    """
    Evaluates repair feasibility deterministically.
    """
    baseline_order = [a.id for a in scenario.agents]
    
    # 1. Run failing trace with mutations
    p_before = create_pipeline(scenario=scenario, order=baseline_order.copy(), llm=llm)
    for m in mutations:
        apply_mutation(p_before, m)
    trace_before = await p_before.run()
    invariants_before = check_all_invariants(trace_before)
    violated = [r for r in invariants_before if not r.passed]

    # Rule 1: Decline immediately for duplicate execution
    for viol in violated:
        if viol.invariant_id == "no_duplicate_execution":
            return RepairVerdict(
                status="DECLINED",
                reason="Duplicate execution already occurred in history. Simulating re-execution cannot undo already-committed side effects. Idempotent compensation required.",
                rerun_agents=[],
                side_effect_ledger=[{"action": "duplicate_execution", "status": "unrecoverable"}],
                residual_violations=[viol.reason or viol.invariant_id],
                all_passed_after=False,
                trace_before_serialized=serialize_trace(trace_before),
                trace_after_serialized=serialize_trace(trace_before)
            )

    # Rule 2: Stale read healing
    # Find stale reader
    from attribution import derive_attribution
    rerun_agents: List[str] = []
    
    for viol in violated:
        attr = derive_attribution(trace_before, viol.invariant_id)
        for reader in attr.stale_readers:
            if reader not in rerun_agents:
                rerun_agents.append(reader)

    if not rerun_agents:
        # Fallback to engineering or QA
        rerun_agents = ["engineering", "qa", "deployment"]

    # Cascade downstream in dependency graph
    agent_dict = {a.id: a for a in scenario.agents}
    order_cascade = rerun_agents.copy()
    stale_keys = {agent_dict[a].writes for a in rerun_agents if a in agent_dict}

    for a_id in baseline_order:
        if a_id in agent_dict and a_id not in order_cascade:
            agent = agent_dict[a_id]
            if any(r in stale_keys for r in agent.reads):
                order_cascade.append(a_id)
                stale_keys.add(agent.writes)

    # Resume simulation using discrete event cascade on the existing state
    await p_before.run_cascade(order_cascade)
    trace_after = p_before.trace
    invariants_after = check_all_invariants(trace_after)
    remaining_viols = [r for r in invariants_after if not r.passed]

    # Side-effect ledger tracking simulated re-executions
    ledger = [{"agent": a_id, "simulated_rerun": True, "side_effects": "simulated_free"} for a_id in order_cascade]

    if not remaining_viols:
        return RepairVerdict(
            status="ACCEPTED",
            reason="All invariants pass and original violation resolved by re-running stale reader and downstream dependencies.",
            rerun_agents=order_cascade,
            side_effect_ledger=ledger,
            residual_violations=[],
            all_passed_after=True,
            trace_before_serialized=serialize_trace(trace_before),
            trace_after_serialized=serialize_trace(trace_after)
        )
    else:
        return RepairVerdict(
            status="DECLINED",
            reason=f"Residual invariant violations remain after re-execution: {', '.join(r.invariant_id for r in remaining_viols)}.",
            rerun_agents=order_cascade,
            side_effect_ledger=ledger,
            residual_violations=[r.reason or r.invariant_id for r in remaining_viols],
            all_passed_after=False,
            trace_before_serialized=serialize_trace(trace_before),
            trace_after_serialized=serialize_trace(trace_after)
        )
