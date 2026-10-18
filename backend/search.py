"""
CUE Wind Tunnel — Adversarial Search

Randomized + greedy search over the mutation parameter space.
Simulated-annealing-style: start random, keep mutations that trigger violations,
mutate further from there, preferring smaller (simpler) mutations.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import List, Optional, Callable, Any

from models import (
    Mutation, MutationType, Event, FailureRecord, SearchProgress,
    SimulationRun,
)
from mutations import (
    run_with_mutation, random_mutation, candidate_reductions
)
from invariants import check_all_invariants, get_violations


# ---------------------------------------------------------------------------
# Population evolution helpers
# ---------------------------------------------------------------------------

def mutate_mutation(mutation: Mutation, scenario) -> Mutation:
    """
    Create a variant of an existing mutation by tweaking its parameters.
    This is the 'neighbor' function in our search.
    """
    m = mutation.model_copy(deep=True)
    agent_ids = [a.id for a in scenario.agents]

    # With some probability, tweak parameters rather than type
    if random.random() < 0.7:
        if m.type == MutationType.DELAY:
            delta = random.choice([-2, -1, 1, 2, 3])
            m.params["delay_seconds"] = max(1, m.params.get("delay_seconds", 2) + delta)

        elif m.type == MutationType.REORDER:
            # Try a different swap partner
            others = [a for a in agent_ids if a != m.target_agent]
            if others: m.params["swap_with"] = random.choice(others)

        elif m.type == MutationType.CONTENT_FLIP:
            # Try different flip_after
            m.params["flip_after"] = random.choice(agent_ids[:3] if len(agent_ids) >= 3 else agent_ids)

        elif m.type == MutationType.REVOKE:
            # Try different revoke_after
            m.params["revoke_after"] = random.choice(agent_ids[:3] if len(agent_ids) >= 3 else agent_ids)

        elif m.type == MutationType.DUPLICATE:
            m.target_agent = random.choice(agent_ids[1:] if len(agent_ids) > 1 else agent_ids)

    else:
        # Change mutation type entirely
        m = random_mutation(scenario)

    return m


def is_smaller(a: Mutation, b: Mutation) -> bool:
    """Is mutation a 'smaller' (simpler) than mutation b?"""
    return a.complexity() < b.complexity()


def evolve(
    population: List[Mutation],
    latest: Mutation,
    found_violation: bool,
    scenario,
) -> List[Mutation]:
    """
    Evolve the population:
    - If violation found, focus search near that mutation (exploitation)
    - If not, add some diversity (exploration)
    """
    new_pop = []

    if found_violation:
        # Exploitation: 70% neighbors of the successful mutation
        for _ in range(7):
            new_pop.append(mutate_mutation(latest, scenario))
        # 30% random for diversity
        for _ in range(3):
            new_pop.append(random_mutation(scenario))
    else:
        # Exploration: keep best half, generate rest randomly
        half = len(population) // 2
        survivors = sorted(population, key=lambda m: m.complexity())[:half]
        new_pop = [mutate_mutation(s, scenario) for s in survivors]
        while len(new_pop) < len(population):
            new_pop.append(random_mutation(scenario))

    return new_pop


# ---------------------------------------------------------------------------
# Main search loop
# ---------------------------------------------------------------------------

async def adversarial_search(
    scenario,
    budget: int = 40,
    seed: Optional[int] = None,
    on_progress: Optional[Callable[[SearchProgress], Any]] = None,
) -> Optional[FailureRecord]:
    """
    Search for the smallest mutation that causes an invariant violation.

    Args:
        scenario: The pipeline configuration to search
        budget: Maximum number of mutations to try
        seed: Random seed for reproducibility
        on_progress: Callback for progress updates

    Returns:
        FailureRecord if a violation was found, None otherwise
    """
    if seed is not None:
        random.seed(seed)

    best_failing: Optional[FailureRecord] = None
    
    # Seed population with key perturbation archetypes + random exploration
    agent_ids = [a.id for a in scenario.agents]
    commitment_keys = [a.writes for a in scenario.agents if a.writes]
    
    population = []
    # Targeted candidate 1: Content flip causing split-brain
    if commitment_keys and len(agent_ids) >= 2:
        population.append(Mutation(
            type=MutationType.CONTENT_FLIP,
            target_agent=agent_ids[0],
            target_key=commitment_keys[0],
            params={"from_value": "oauth", "to_value": "saml", "flip_after": agent_ids[1] if len(agent_ids) > 1 else agent_ids[0]}
        ))
    # Targeted candidate 2: Duplicate action
    if len(agent_ids) >= 2:
        population.append(Mutation(
            type=MutationType.DUPLICATE,
            target_agent=agent_ids[-2],
            target_key=commitment_keys[-1] if commitment_keys else "",
            params={}
        ))
    # Fill remaining with random mutations
    while len(population) < 10:
        population.append(random_mutation(scenario))

    discarded_runs_count = 0
    violation_counts_by_type = {}

    for i in range(budget):
        if not population and best_failing:
            mutations = candidate_reductions(best_failing.mutation, scenario)
            population = [m for m in mutations if is_smaller(m, best_failing.mutation)]

        if not population:
            mutation = random_mutation(scenario)
        else:
            mutation = population.pop(0)

        # Run the pipeline with this mutation
        try:
            result = await run_with_mutation(mutation, scenario)
        except Exception:
            discarded_runs_count += 1
            continue

        # Check for violations
        violations = [r for r in result.invariant_results if not r.passed]
        found = len(violations) > 0

        violation_text = violations[0].reason if violations else None
        invariant_id = violations[0].invariant_id if violations else ""

        if found and violation_text:
            failure = FailureRecord(
                mutation=mutation,
                trace=result.trace,
                violation=violation_text,
                invariant_id=invariant_id,
            )
            if best_failing is None or is_smaller(mutation, best_failing.mutation):
                best_failing = failure

        # Evolve population
        population = evolve(population, mutation, found, scenario)

        # Report progress
        if on_progress:
            progress = SearchProgress(
                step=i + 1,
                total=budget,
                mutation=mutation,
                passed=not found,
                violation=violation_text,
                best_failure=best_failing,
            )
            result = on_progress(progress)
            if asyncio.iscoroutine(result):
                await result

    return best_failing
