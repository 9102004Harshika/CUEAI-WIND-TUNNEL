"""
CUE Wind Tunnel — Deterministic Trace Attribution
Derives culpability directly from the trace event graph.
CRITICAL RULE: Never derives culprits by parsing error or violation strings.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from models import Event, Commitment, AgentAction, InvariantResult

class AttributionResult(BaseModel):
    invariant_id: str
    change_source: Optional[str] = None      # Agent that wrote or duplicated the newer/conflicting version
    stale_readers: List[str] = Field(default_factory=list) # Agents that acted upon the outdated version
    duplicate_executor: Optional[str] = None # Agent that executed multiple times with identical inputs
    target_key: Optional[str] = None         # Fact key in question
    stale_version_read: Optional[int] = None # Version read by stale reader
    latest_version: Optional[int] = None     # Current latest version of target key
    event_indexes: List[int] = Field(default_factory=list) # Trace indices of relevant events
    call_site: Optional[Dict[str, Any]] = None # Function and line info where available

def derive_attribution(trace: List[Event], invariant_id: str) -> AttributionResult:
    """
    Pure deterministic attribution computed solely over the trace events.
    """
    commitments: Dict[str, Commitment] = {}
    key_versions: Dict[str, List[Commitment]] = {}
    actions: List[AgentAction] = []
    
    for idx, e in enumerate(trace):
        if isinstance(e, Commitment):
            commitments[e.id] = e
            key_versions.setdefault(e.key, []).append(e)
        elif isinstance(e, AgentAction):
            actions.append(e)

    # 1. Stale read / Downstream disagreement
    if invariant_id in ("no_stale_commitment", "no_downstream_disagreement", "no_deploy_without_current_approval"):
        for act_idx, act in enumerate(trace):
            if not isinstance(act, AgentAction):
                continue
            for r_idx, r_id in enumerate(act.reads):
                if r_id in commitments:
                    c_read = commitments[r_id]
                    # Check if there is a newer commitment for this key
                    all_for_key = key_versions.get(c_read.key, [])
                    latest_commit = max(all_for_key, key=lambda c: c.version) if all_for_key else c_read
                    
                    if latest_commit.version > c_read.version:
                        # Found stale read!
                        # change_source = agent that wrote the newer version
                        # stale_reader = act.agent_id
                        return AttributionResult(
                            invariant_id=invariant_id,
                            change_source=latest_commit.agent_id,
                            stale_readers=[act.agent_id],
                            target_key=c_read.key,
                            stale_version_read=c_read.version,
                            latest_version=latest_commit.version,
                            event_indexes=[act_idx, trace.index(latest_commit)],
                            call_site={"agent": act.agent_id, "action_type": act.action_type, "step": "act"}
                        )

    # 2. Duplicate execution
    if invariant_id == "no_duplicate_execution":
        seen_fingerprints: Dict[tuple, int] = {}
        for act_idx, e in enumerate(trace):
            if isinstance(e, AgentAction):
                fp = (e.agent_id, e.action_type, tuple(sorted(e.reads_versions)))
                if fp in seen_fingerprints:
                    prior_idx = seen_fingerprints[fp]
                    return AttributionResult(
                        invariant_id=invariant_id,
                        change_source=e.agent_id,
                        duplicate_executor=e.agent_id,
                        event_indexes=[prior_idx, act_idx],
                        call_site={"agent": e.agent_id, "action_type": e.action_type, "duplicate": True}
                    )
                seen_fingerprints[fp] = act_idx

    # 3. Action on revoked commitment
    if invariant_id == "no_action_on_revoked":
        for act_idx, act in enumerate(trace):
            if not isinstance(act, AgentAction):
                continue
            for r_id in act.reads:
                c = commitments.get(r_id)
                if c and c.revoked and (c.revoked_at or c.created_at) < act.executed_at:
                    return AttributionResult(
                        invariant_id=invariant_id,
                        change_source=c.agent_id, # Creator of revoked commitment
                        stale_readers=[act.agent_id],
                        target_key=c.key,
                        event_indexes=[trace.index(c), act_idx],
                        call_site={"agent": act.agent_id, "action_type": act.action_type}
                    )

    # 4. Fallback if goal rule failure
    return AttributionResult(
        invariant_id=invariant_id,
        change_source=trace[0].agent_id if trace else "unknown",
        event_indexes=[0] if trace else []
    )
