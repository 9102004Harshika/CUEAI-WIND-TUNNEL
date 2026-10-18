"""
CUE Wind Tunnel — Shrinker

QuickCheck-style shrinking: iteratively reduce mutation parameters,
keeping the smallest mutation that still triggers an invariant violation.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from models import Mutation, FailureRecord
from mutations import run_with_mutation, candidate_reductions
from invariants import get_violations


async def shrink(failure: FailureRecord, scenario=None, max_rounds: int = 20) -> FailureRecord:
    """
    Shrink a failing mutation to the minimal version that still fails.

    Tries removing/reducing each parameter independently, keeping
    the smallest version that still triggers the invariant violation.
    """
    current = failure
    improved = True
    rounds = 0

    while improved and rounds < max_rounds:
        improved = False
        rounds += 1

        candidates = candidate_reductions(current.mutation, scenario)
        if not candidates:
            break

        for smaller in candidates:
            try:
                result = await run_with_mutation(smaller, scenario)
            except Exception:
                continue

            violations = [r for r in result.invariant_results if not r.passed]

            if violations:
                # Found a smaller mutation that still fails!
                new_failure = FailureRecord(
                    mutation=smaller,
                    trace=result.trace,
                    violation=violations[0].reason or current.violation,
                    invariant_id=violations[0].invariant_id,
                    shrunk=True,
                )

                if smaller.complexity() < current.mutation.complexity():
                    current = new_failure
                    improved = True
                    break  # Restart reduction from the new smaller baseline

    current.shrunk = True
    return current
