"""
CUE Wind Tunnel — Mutation Engine

Perturber that applies parameterized mutations to pipeline runs.
5 mutation types: delay, reorder, revoke, duplicate, content_flip.
"""
from __future__ import annotations

import asyncio
import copy
import time
import random
from typing import List, Optional, Dict, Any, Callable

from models import (
    Commitment, AgentAction, Event, Mutation, MutationType,
    InvariantResult, SimulationRun, FailureRecord,
)
from pipeline import PipelineRunner, CommitmentStore, create_pipeline
from invariants import check_all_invariants, get_violations


# ---------------------------------------------------------------------------
# Mutation applicators
# ---------------------------------------------------------------------------

def apply_delay(pipeline: PipelineRunner, mutation: Mutation):
    """Hold up delivery of a commitment to a target agent by N seconds."""
    delay_seconds = mutation.params.get("delay_seconds", 2)
    target_agent = mutation.target_agent
    if mutation.type == MutationType.DELAY:
        delay = mutation.params.get("delay_seconds", 5)
        pipeline.set_agent_delay(mutation.target_agent, float(delay))


def apply_reorder(pipeline: PipelineRunner, mutation: Mutation):
    """Swap execution order of two agents."""
    if mutation.type == MutationType.REORDER:
        # Instead of arbitrary swaps that crash, we shuffle the initial pool.
        # The Discrete Event Simulator automatically enforces topological safety,
        # so shuffling tests valid, alternate tie-breaking schedules natively.
        import random
        random.shuffle(pipeline.order)


def apply_revoke(pipeline: PipelineRunner, mutation: Mutation):
    """
    After a target agent has read a commitment, revoke/change it
    before a downstream agent acts. This is the classic stale-read bug.
    """
    target_key = mutation.target_key
    # The revocation happens AFTER the first reader but BEFORE downstream
    revoke_after = mutation.params.get("revoke_after", "engineering")
    new_value = mutation.params.get("new_value", None)

    def revoke_hook(store: CommitmentStore, trace: List[Event]):
        if not getattr(revoke_hook, "has_fired", False):
            if new_value:
                # Content change (new version)
                c = store.update_value(target_key, new_value)
                if c:
                    trace.append(c)
            else:
                # Simple revocation
                c = store.revoke(target_key)
                if c:
                    trace.append(c)
            revoke_hook.has_fired = True

    if revoke_after:
        pipeline.add_post_hook(revoke_after, revoke_hook)


def apply_duplicate(pipeline: PipelineRunner, mutation: Mutation):
    """Deliver the same commitment twice to cause duplicate processing."""
    target_agent = mutation.target_agent
    if target_agent and target_agent in pipeline.order:
        # Actually force the agent to execute a second time by pushing it to the back
        pipeline.order.append(target_agent)


def apply_content_flip(pipeline: PipelineRunner, mutation: Mutation):
    """
    Flip a decision value (e.g. OAuth->SAML) after it's already been read.
    This is the most dangerous mutation: creates a split-brain scenario.
    """
    target_key = mutation.target_key or mutation.params.get("target_key", "implemented_protocol")
    from_value = mutation.params.get("from_value", "oauth")
    to_value = mutation.params.get("to_value", "saml")
    flip_after = mutation.params.get("flip_after", "engineering")

    def flip_hook(store: CommitmentStore, trace: List[Event]):
        if not getattr(flip_hook, "has_fired", False):
            # Only trigger once! Otherwise repairing re-triggers the fault forever.
            c = store.update_value(target_key, to_value)
            if c:
                trace.append(c)
                # also emit a mutation_applied event to make it clear in the trace
                from models import AgentAction
                trace.append(AgentAction(
                    agent_id="system", action_type="content_flip", reads=[c.id], 
                    reads_versions=[c.version], produced_commitment_id=c.id, 
                    executed_at=getattr(store, '_clock', 0.0)
                ))
            flip_hook.has_fired = True

    if flip_after:
        pipeline.add_post_hook(flip_after, flip_hook)


# ---------------------------------------------------------------------------
# Mutation applicator dispatch
# ---------------------------------------------------------------------------

APPLICATORS = {
    MutationType.DELAY: apply_delay,
    MutationType.REORDER: apply_reorder,
    MutationType.REVOKE: apply_revoke,
    MutationType.DUPLICATE: apply_duplicate,
    MutationType.CONTENT_FLIP: apply_content_flip,
}


def apply_mutation(pipeline: PipelineRunner, mutation: Mutation):
    """Apply a mutation to a pipeline runner."""
    applicator = APPLICATORS.get(mutation.type)
    if not applicator:
        raise ValueError(f"Unknown mutation type: {mutation.type}")
    applicator(pipeline, mutation)


# ---------------------------------------------------------------------------
# Run pipeline with mutation + check invariants
# ---------------------------------------------------------------------------

async def run_with_mutation(
    mutation: Mutation,
    scenario,
    order: Optional[List[str]] = None,
) -> SimulationRun:
    """Run the pipeline with a mutation applied, return full results."""
    pipeline = create_pipeline(scenario=scenario, order=order)
    apply_mutation(pipeline, mutation)

    trace = await pipeline.run()
    results = check_all_invariants(trace)
    violations = get_violations(results)

    return SimulationRun(
        scenario=mutation.model_dump(),
        mutation=mutation,
        trace=trace,
        invariant_results=results,
        violated_invariants=[r.invariant_id for r in violations],
    )


# ---------------------------------------------------------------------------
# Mutation generators
# ---------------------------------------------------------------------------

def random_mutation(scenario) -> Mutation:
    """Generate a random mutation for the adversarial search."""
    agent_ids = [a.id for a in scenario.agents]
    commitment_keys = [a.writes for a in scenario.agents if a.writes]
    mut_type = random.choice(list(MutationType))

    if mut_type == MutationType.DELAY:
        return Mutation(
            type=mut_type,
            target_agent=random.choice(agent_ids),
            target_key=random.choice(commitment_keys) if commitment_keys else "",
            params={"delay_seconds": random.randint(1, 10)},
        )

    if mut_type == MutationType.REORDER:
        agents = random.sample(agent_ids, 2) if len(agent_ids) >= 2 else agent_ids * 2
        return Mutation(
            type=mut_type,
            target_agent=agents[0],
            target_key="",
            params={"swap_with": agents[1]},
        )

    if mut_type == MutationType.REVOKE:
        key = random.choice(commitment_keys) if commitment_keys else ""
        revoke_after = random.choice(agent_ids)
        return Mutation(
            type=mut_type,
            target_agent=revoke_after,
            target_key=key,
            params={"revoke_after": revoke_after},
        )

    if mut_type == MutationType.DUPLICATE:
        return Mutation(
            type=mut_type,
            target_agent=random.choice(agent_ids[1:] if len(agent_ids) > 1 else agent_ids),
            target_key=random.choice(commitment_keys) if commitment_keys else "",
            params={},
        )

    if mut_type == MutationType.CONTENT_FLIP:
        realistic_values = ["saml", "oidc", "token_refresh", "legacy_auth", "expired_cert", "revoked", "v2_api", "disabled"]
        return Mutation(
            type=mut_type,
            target_agent=random.choice(agent_ids),
            target_key=random.choice(commitment_keys) if commitment_keys else "",
            params={
                "from_value": "oauth",
                "to_value": random.choice(realistic_values),
                "flip_after": random.choice(agent_ids),
            },
        )

    return Mutation(type=mut_type, target_agent=random.choice(agent_ids))


def candidate_reductions(mutation: Mutation, scenario) -> List[Mutation]:
    """
    Generate simpler variants of a mutation (for the shrinker).
    Each candidate is a reduction along one dimension.
    """
    candidates = []
    agent_ids = [a.id for a in scenario.agents]

    if mutation.type == MutationType.DELAY:
        delay = mutation.params.get("delay_seconds", 2)
        if delay > 1:
            candidates.append(Mutation(
                type=mutation.type,
                target_agent=mutation.target_agent,
                target_key=mutation.target_key,
                params={"delay_seconds": delay - 1},
            ))
            candidates.append(Mutation(
                type=mutation.type,
                target_agent=mutation.target_agent,
                target_key=mutation.target_key,
                params={"delay_seconds": delay // 2},
            ))

    if mutation.type == MutationType.CONTENT_FLIP:
        # Try with different flip_after points
        flip_after = mutation.params.get("flip_after", "")
        for agent in agent_ids:
            if agent != flip_after:
                candidates.append(Mutation(
                    type=mutation.type,
                    target_agent=mutation.target_agent,
                    target_key=mutation.target_key,
                    params={**mutation.params, "flip_after": agent},
                ))

    if mutation.type == MutationType.REORDER:
        # Try swapping adjacent agents instead of distant ones
        swap = mutation.params.get("swap_with", "")
        if swap in agent_ids and mutation.target_agent in agent_ids:
            idx1 = agent_ids.index(mutation.target_agent)
            idx2 = agent_ids.index(swap)
            if abs(idx1 - idx2) > 1:
                # Try a closer swap
                mid = (idx1 + idx2) // 2
                candidates.append(Mutation(
                    type=mutation.type,
                    target_agent=mutation.target_agent,
                    target_key=mutation.target_key,
                    params={"swap_with": agent_ids[mid]},
                ))

    return candidates
