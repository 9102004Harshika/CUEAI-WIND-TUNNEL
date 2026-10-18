"""
CUE Wind Tunnel — Run Search CLI

Usage:
    python run_search.py --budget 40 --runs 1
    python run_search.py --budget 40 --runs 10
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys
import time

from models import SearchProgress, FailureRecord
from search import adversarial_search
from shrinker import shrink


def print_progress(progress: SearchProgress):
    """Live progress output."""
    status = "❌ FAIL" if not progress.passed else "✅ pass"
    mut_desc = progress.mutation.describe()
    best = ""
    if progress.best_failure:
        best = f"  [best: {progress.best_failure.mutation.complexity():.1f}]"
    print(f"  [{progress.step:3d}/{progress.total}] {status}  {mut_desc}{best}")


async def run_single_search(budget: int, seed: int, verbose: bool = True) -> dict:
    """Run one search + shrink pass. Returns stats dict."""
    start = time.time()
    first_failure_step = None

    def on_progress(p: SearchProgress):
        nonlocal first_failure_step
        if not p.passed and first_failure_step is None:
            first_failure_step = p.step
        if verbose:
            print_progress(p)

    if verbose:
        print(f"\n{'='*70}")
        print(f"  Search run (seed={seed}, budget={budget})")
        print(f"{'='*70}")

    failure = await adversarial_search(
        budget=budget,
        seed=seed,
        on_progress=on_progress,
    )

    elapsed = time.time() - start

    if failure:
        if verbose:
            print(f"\n  🎯 Violation found! Shrinking...")

        shrunk = await shrink(failure)

        if verbose:
            print(f"\n  {'─'*60}")
            print(f"  MINIMAL FAILURE:")
            print(f"  Mutation:   {shrunk.mutation.describe()}")
            print(f"  Complexity: {shrunk.mutation.complexity():.1f}")
            print(f"  Invariant:  {shrunk.invariant_id}")
            print(f"  Violation:  {shrunk.violation}")
            print(f"  Shrunk:     {shrunk.shrunk}")
            print(f"  Time:       {elapsed:.1f}s")
            print(f"  {'─'*60}")

        return {
            "found": True,
            "first_failure_step": first_failure_step,
            "mutation": shrunk.mutation.describe(),
            "mutation_type": shrunk.mutation.type.value,
            "complexity": shrunk.mutation.complexity(),
            "invariant": shrunk.invariant_id,
            "violation": shrunk.violation,
            "shrunk": shrunk.shrunk,
            "elapsed": elapsed,
        }
    else:
        if verbose:
            print(f"\n  ✅ No violation found in {budget} mutations ({elapsed:.1f}s)")
        return {
            "found": False,
            "elapsed": elapsed,
        }


async def run_multiple(budget: int, runs: int, verbose: bool = True):
    """Run search multiple times and report aggregate stats."""
    all_results = []

    for i in range(runs):
        seed = i * 42 + 7  # Deterministic but different seeds
        result = await run_single_search(
            budget=budget,
            seed=seed,
            verbose=verbose,
        )
        all_results.append(result)

    # Aggregate stats
    found_count = sum(1 for r in all_results if r["found"])
    found_results = [r for r in all_results if r["found"]]

    print(f"\n{'='*70}")
    print(f"  CUE WIND TUNNEL — Search Results Summary")
    print(f"{'='*70}")
    print(f"  Search budget: {budget} mutations per run")
    print(f"  Runs:          {runs}")
    print(f"  Runs that found a genuine invariant violation: {found_count}/{runs}")

    if found_results:
        avg_steps = sum(r["first_failure_step"] for r in found_results) / len(found_results)
        avg_time = sum(r["elapsed"] for r in found_results) / len(found_results)
        min_complexity = min(r["complexity"] for r in found_results)
        smallest = min(found_results, key=lambda r: r["complexity"])

        print(f"  Average mutations to first failure: {avg_steps:.1f}")
        print(f"  Average time per run: {avg_time:.1f}s")
        print(f"  Smallest failure complexity: {min_complexity:.1f}")
        print(f"  Smallest failure found: {smallest['mutation']}")
        print(f"  Violated invariant: {smallest['invariant']}")
        print(f"  Violation: {smallest['violation']}")

    print(f"{'='*70}\n")

    return all_results


def main():
    parser = argparse.ArgumentParser(description="CUE Wind Tunnel — Adversarial Search")
    parser.add_argument("--budget", type=int, default=40, help="Mutations per run")
    parser.add_argument("--runs", type=int, default=1, help="Number of search runs")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-step output")
    args = parser.parse_args()

    results = asyncio.run(run_multiple(
        budget=args.budget,
        runs=args.runs,
        verbose=not args.quiet,
    ))

    # Write results to file
    with open("search_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"📊 Results saved to search_results.json")


if __name__ == "__main__":
    main()
