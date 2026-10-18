"""
CUE Wind Tunnel — Check Invariants CLI

Usage:
    python check_invariants.py trace.json
    python check_invariants.py --run-baseline
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys

from models import Commitment, AgentAction, Event
from invariants import check_all_invariants, get_violations


def load_trace_from_json(filepath: str) -> list:
    """Load a trace from a JSON file and reconstruct typed events."""
    with open(filepath) as f:
        raw = json.load(f)

    trace = []
    for item in raw:
        event_type = item.pop("event_type", None)
        if event_type == "commitment":
            trace.append(Commitment(**item))
        elif event_type == "action":
            trace.append(AgentAction(**item))
        else:
            # Try to guess by presence of 'key' field
            if "key" in item:
                trace.append(Commitment(**item))
            elif "action_type" in item:
                trace.append(AgentAction(**item))
    return trace


def print_results(results):
    """Pretty-print invariant check results."""
    print("\n" + "=" * 70)
    print("  CUE WIND TUNNEL — Invariant Check Results")
    print("=" * 70)

    all_pass = True
    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        if not r.passed:
            all_pass = False
        print(f"\n  {status}  {r.invariant_id}")
        print(f"         {r.invariant_description}")
        if r.reason:
            print(f"         Reason: {r.reason}")

    print("\n" + "-" * 70)
    if all_pass:
        print("  🎯 All invariants PASSED")
    else:
        violations = get_violations(results)
        print(f"  WARNING:️  {len(violations)} invariant(s) VIOLATED")
    print("=" * 70 + "\n")

    return all_pass


async def run_baseline_check():
    """Run baseline pipeline and check all invariants."""
    from run_pipeline import run_baseline
    trace = await run_baseline()
    results = check_all_invariants(trace)
    return results


def main():
    parser = argparse.ArgumentParser(description="CUE Wind Tunnel — Invariant Checker")
    parser.add_argument("trace_file", nargs="?", help="Path to trace JSON file")
    parser.add_argument(
        "--run-baseline", action="store_true",
        help="Run baseline pipeline and check invariants (no file needed)"
    )
    args = parser.parse_args()

    if args.run_baseline:
        results = asyncio.run(run_baseline_check())
    elif args.trace_file:
        trace = load_trace_from_json(args.trace_file)
        results = check_all_invariants(trace)
    else:
        print("Error: provide a trace file or use --run-baseline")
        sys.exit(1)

    all_pass = print_results(results)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
