"""
CUE Wind Tunnel — Invariant Checker

Plain Python predicates over traces.
Each returns None on PASS, or a human-readable reason string on FAIL.
"""

from __future__ import annotations

from typing import List, Optional, Union, Dict
from models import Commitment, AgentAction, Event, InvariantResult, Invariant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def commitments_in_trace(trace: List[Event]) -> List[Commitment]:
    """Extract all Commitment events from a trace."""
    return [e for e in trace if isinstance(e, Commitment)]


def actions_in_trace(trace: List[Event]) -> List[AgentAction]:
    """Extract all AgentAction events from a trace."""
    return [e for e in trace if isinstance(e, AgentAction)]


def latest_commitment(trace: List[Event], key: str) -> Optional[Commitment]:
    """Get the latest commitment for a given key from the trace (including revoked)."""
    matches = [e for e in trace if isinstance(e, Commitment) and e.key == key]
    if not matches:
        return None
    # Return the one with highest version
    return max(matches, key=lambda c: c.version)


def latest_usable_commitment(trace: List[Event], key: str) -> Optional[Commitment]:
    """Get the latest non-revoked, usable commitment for a given key."""
    matches = [e for e in trace if isinstance(e, Commitment) and e.key == key and not e.revoked]
    if not matches:
        return None
    return max(matches, key=lambda c: c.version)


def commitment_by_id(trace: List[Event], cid: str) -> Optional[Commitment]:
    """Find a commitment by its ID."""
    for e in trace:
        if isinstance(e, Commitment) and e.id == cid:
            return e
    return None


# ---------------------------------------------------------------------------
# Invariant 1: No deployment without current approval
# ---------------------------------------------------------------------------

def no_deploy_without_current_approval(trace: List[Event]) -> Optional[str]:
    """
    DeploymentAgent may only execute if it read the CURRENT version
    of QA approval. Deployment on a stale approval is a violation.
    """
    active_commitments = [
        c for c in commitments_in_trace(trace) 
        if not c.revoked and c == latest_usable_commitment(trace, c.key)
    ]
    active_ids = {c.id for c in active_commitments}
    
    dep_actions = [
        e for e in trace 
        if isinstance(e, AgentAction) and e.action_type in ("execute_deployment", "deploy_service", "deploy_blocked")
    ]
    if not dep_actions:
        return None
        
    active_dep_actions = [e for e in dep_actions if e.produced_commitment_id in active_ids]
    target_actions = active_dep_actions if active_dep_actions else [dep_actions[-1]]

    for event in target_actions:
        # Find the latest usable QA approval in the trace
        approval = latest_usable_commitment(trace, key="qa_approval")
        if not approval:
            # If deployment blocked itself safely, this is not an invalid execution
            if event.action_type == "deploy_blocked":
                continue
            return "Deployment executed but no valid QA approval exists in trace"

        if event.action_type in ("execute_deployment", "deploy_service"):
            # Check if deployment read the current version
            if approval.id in event.reads:
                idx = event.reads.index(approval.id)
                read_version = event.reads_versions[idx]
                if read_version != approval.version:
                    return (
                        f"Deployment acted on stale approval v{read_version}, "
                        f"current is v{approval.version}"
                    )
            else:
                for rid, rv in zip(event.reads, event.reads_versions):
                    c = commitment_by_id(trace, rid)
                    if c and c.key == "qa_approval":
                        if c.version != approval.version:
                            return (
                                f"Deployment read approval {rid[:8]}... v{rv}, "
                                f"but latest approval is v{approval.version}"
                            )
                        break

    return None


# ---------------------------------------------------------------------------
# Invariant 2: No downstream disagreement
# ---------------------------------------------------------------------------

def no_downstream_disagreement(trace: List[Event]) -> Optional[str]:
    """
    Any active (latest, non-revoked) commitment must not be based on a STALE 
    upstream dependency. If it is, the system has a split brain.
    """
    active_commitments = [
        c for c in commitments_in_trace(trace) 
        if not c.revoked and c == latest_usable_commitment(trace, c.key)
    ]
    active_ids = {c.id for c in active_commitments}
    
    violations = []
    for event in actions_in_trace(trace):
        if event.produced_commitment_id in active_ids:
            for r_id in event.reads:
                c = commitment_by_id(trace, r_id)
                if c:
                    up_latest = latest_usable_commitment(trace, c.key)
                    if up_latest and up_latest.id != r_id:
                        prod = commitment_by_id(trace, event.produced_commitment_id)
                        vol_text = f"{prod.agent_id}'s active '{prod.key}' is based on a stale read of '{c.key}' (v{up_latest.version} exists)"
                        violations.append(vol_text)
                        
    if violations:
        return " | ".join(violations)
    return None


# ---------------------------------------------------------------------------
# Invariant 3: No action on revoked commitment
# ---------------------------------------------------------------------------

def no_action_on_revoked_commitment(trace: List[Event]) -> Optional[str]:
    """
    No agent may execute an action that reads a commitment that was
    already revoked/superseded at the time of execution.
    """
    # Build a map of commitment_id → time it was superseded/revoked
    superseded_at: Dict[str, float] = {}

    for event in trace:
        if isinstance(event, Commitment):
            if event.revoked:
                superseded_at[event.id] = event.revoked_at if event.revoked_at is not None else event.created_at
            if event.supersedes:
                # The superseded commitment became stale when this new one was created
                superseded_at[event.supersedes] = event.created_at

    for event in trace:
        if not isinstance(event, AgentAction):
            continue
        for read_id in event.reads:
            if read_id in superseded_at:
                # Only a violation if the commitment was superseded BEFORE the action
                if superseded_at[read_id] < event.executed_at:
                    c = commitment_by_id(trace, read_id)
                    key_info = f" ({c.key}={c.value})" if c else ""
                    return (
                        f"{event.agent_id} executed '{event.action_type}' reading "
                        f"superseded commitment {read_id[:8]}...{key_info}"
                    )

    return None


# ---------------------------------------------------------------------------
# Invariant 4: No duplicate execution
# ---------------------------------------------------------------------------

def no_duplicate_execution(trace: List[Event]) -> Optional[str]:
    """
    The same action type should not execute twice by the same agent
    with the same read set (indicates duplicate delivery caused re-execution).
    """
    seen = set()
    for event in trace:
        if not isinstance(event, AgentAction):
            continue
        # Fingerprint: agent + action_type + sorted reads
        fingerprint = (
            event.agent_id,
            event.action_type,
            tuple(sorted(zip(event.reads, event.reads_versions))),
        )
        if fingerprint in seen:
            return (
                f"{event.agent_id} executed '{event.action_type}' twice "
                f"with the same read set"
            )
        seen.add(fingerprint)

    return None


# ---------------------------------------------------------------------------
# Invariant 5: No blocked executions
# ---------------------------------------------------------------------------

def no_blocked_executions(trace: List[Event]) -> Optional[str]:
    """
    Agents must successfully execute without being blocked by missing
    or revoked dependencies.
    """
    for event in trace:
        if isinstance(event, AgentAction) and event.action_type == "execution_blocked":
            reason = event.payload.get("reason", "unknown reason")
            return f"{event.agent_id} was blocked at the action boundary: {reason}"
    return None


# ---------------------------------------------------------------------------
# Invariant 6: Authoritative Goal Invariant (SSO Safe Deployment)
# ---------------------------------------------------------------------------

def goal_sso_safe_deployment(trace: List[Event]) -> Optional[str]:
    """
    Authoritative Goal Invariant: Independently verifies the terminal business outcome.
    SSO Policy:
    1. Required protocol commitments (auth_protocol, implemented_protocol) must exist and be non-revoked.
    2. If auth_protocol != implemented_protocol:
       - Deployment MUST NOT deploy (deploy_action must be 'hold' or deploy_blocked).
    3. If auth_protocol == implemented_protocol:
       - QA approval must exist and be 'approved'. If not approved, deployment must hold.
       - If QA is approved, deployment must be 'deploy'.
    4. Missing QA decision or deployment decision when execution was expected fails the goal.
    """
    auth = latest_usable_commitment(trace, "auth_protocol")
    impl = latest_usable_commitment(trace, "implemented_protocol")
    
    if not auth or not impl:
        return "Goal Invariant Failed: Required protocol commitment ('auth_protocol' or 'implemented_protocol') is missing or revoked"
        
    qa = latest_usable_commitment(trace, "qa_approval")
    deploy_comm = latest_usable_commitment(trace, "deploy_action")
    
    dep_actions = [e for e in trace if isinstance(e, AgentAction) and e.agent_id == "deployment"]
    latest_dep_action = dep_actions[-1] if dep_actions else None
    
    deploy_decision = None
    if deploy_comm:
        deploy_decision = deploy_comm.value
    elif latest_dep_action:
        if latest_dep_action.action_type == "deploy_blocked":
            deploy_decision = "hold"
        else:
            deploy_decision = latest_dep_action.payload.get("decision") or latest_dep_action.payload.get("decision_result")
            
    # Case A: Protocol mismatch (e.g. auth=oauth, impl=saml)
    if auth.value != impl.value:
        if deploy_decision != "hold":
            return f"Goal Invariant Failed: Protocol mismatch ({auth.value} != {impl.value}) requires deployment hold, but outcome was '{deploy_decision}'"
        return None
        
    # Case B: Protocols match
    if not qa:
        return "Goal Invariant Failed: Missing or revoked QA approval on matching protocols"
        
    if qa.value != "approved":
        if deploy_decision != "hold":
            return f"Goal Invariant Failed: Unapproved QA ('{qa.value}') requires deployment hold, but outcome was '{deploy_decision}'"
        return None
        
    if deploy_decision != "deploy":
        return f"Goal Invariant Failed: Matching protocols with QA approval require 'deploy', but outcome was '{deploy_decision}'"
        
    return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_INVARIANTS = [
    Invariant(
        id="no_deploy_without_current_approval",
        description="Deployment must read the CURRENT version of QA approval",
        check_fn="no_deploy_without_current_approval",
        scope=["qa_approval", "deploy_service"],
    ),
    Invariant(
        id="no_downstream_disagreement",
        description="Any active commitment must not be based on a stale upstream dependency",
        check_fn="no_downstream_disagreement",
        scope=["*"],
    ),
    Invariant(
        id="no_action_on_revoked",
        description="No agent may act on a revoked or superseded commitment",
        check_fn="no_action_on_revoked_commitment",
        scope=["*"],
    ),
    Invariant(
        id="no_duplicate_execution",
        description="Same action must not execute twice with identical reads",
        check_fn="no_duplicate_execution",
        scope=["*"],
    ),
    Invariant(
        id="no_blocked_executions",
        description="Execution gates must not block agents due to missing/revoked deps",
        check_fn="no_blocked_executions",
        scope=["*"],
    ),
    Invariant(
        id="goal_sso_safe_deployment",
        description="SSO goal policy: valid approval allows deployment, mismatches require hold",
        check_fn="goal_sso_safe_deployment",
        scope=["auth_protocol", "implemented_protocol", "qa_approval", "deploy_action"],
    ),
]

INVARIANT_FUNCTIONS = {
    "no_deploy_without_current_approval": no_deploy_without_current_approval,
    "no_downstream_disagreement": no_downstream_disagreement,
    "no_action_on_revoked_commitment": no_action_on_revoked_commitment,
    "no_duplicate_execution": no_duplicate_execution,
    "no_blocked_executions": no_blocked_executions,
    "goal_sso_safe_deployment": goal_sso_safe_deployment,
}


def check_all_invariants(trace: List[Event]) -> List[InvariantResult]:
    """Run all invariants against a trace. Returns list of results."""
    results = []
    for inv in ALL_INVARIANTS:
        fn = INVARIANT_FUNCTIONS.get(inv.check_fn)
        if not fn:
            results.append(InvariantResult(
                invariant_id=inv.id,
                invariant_description=inv.description,
                passed=False,
                reason=f"Unknown check function: {inv.check_fn}",
            ))
            continue

        reason = fn(trace)
        results.append(InvariantResult(
            invariant_id=inv.id,
            invariant_description=inv.description,
            passed=(reason is None),
            reason=reason,
        ))

    return results


def get_violations(results: List[InvariantResult]) -> List[InvariantResult]:
    """Filter to only violated invariants."""
    return [r for r in results if not r.passed]
