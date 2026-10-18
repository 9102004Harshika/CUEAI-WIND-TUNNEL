"""
CUE Wind Tunnel — Run Pipeline CLI

Usage:
    python run_pipeline.py --scenario baseline
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys

from models import Commitment, AgentAction
from pipeline import create_pipeline
from llm_client import get_llm_client


def serialize_trace(trace) -> list:
    """Convert trace events to JSON-serializable dicts."""
    result = []
    for event in trace:
        d = event.model_dump()
        d["event_type"] = event.event_type
        result.append(d)
    return result


def print_trace(trace, format="pretty"):
    """Print trace to console."""
    serialized = serialize_trace(trace)

    if format == "json":
        print(json.dumps(serialized, indent=2))
        return

    # Pretty print
    print("\n" + "=" * 70)
    print("  CUE WIND TUNNEL — Pipeline Trace")
    print("=" * 70)

    for i, event in enumerate(trace):
        prefix = f"  [{i+1}]"
        if isinstance(event, Commitment):
            status = "🔴 REVOKED" if event.revoked else "🟢"
            print(f"\n{prefix} COMMITMENT {status}")
            print(f"      Agent:   {event.agent_id}")
            print(f"      Key:     {event.key} = {event.value} (v{event.version})")
            print(f"      Says:    \"{event.statement}\"")
            if event.supersedes:
                print(f"      Replaces: {event.supersedes[:8]}...")
        elif isinstance(event, AgentAction):
            print(f"\n{prefix} ACTION")
            print(f"      Agent:   {event.agent_id}")
            print(f"      Type:    {event.action_type}")
            print(f"      Reads:   {len(event.reads)} commitment(s)")
            for rid, rv in zip(event.reads, event.reads_versions):
                print(f"               → {rid[:8]}... v{rv}")
            if event.payload:
                print(f"      Payload: {json.dumps(event.payload)}")

    print("\n" + "=" * 70)
    print(f"  Total events: {len(trace)}")
    print("=" * 70 + "\n")


async def run_baseline(use_gemini: bool = False) -> list:
    """Run the baseline (unperturbed) pipeline."""
    llm = get_llm_client(use_gemini=use_gemini)
    from scenarios import SSO_SCENARIO
    pipeline = create_pipeline(scenario=SSO_SCENARIO, llm=llm)
    
    print("Running end-to-end multi-agent pipeline...")
    trace = await pipeline.run()
    return trace


def main():
    parser = argparse.ArgumentParser(description="CUE Wind Tunnel — Pipeline Runner")
    parser.add_argument(
        "--scenario", default="baseline",
        help="Scenario to run (default: baseline)"
    )
    parser.add_argument(
        "--format", default="pretty", choices=["pretty", "json"],
        help="Output format"
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Write trace JSON to file"
    )
    parser.add_argument(
        "--gemini", action="store_true",
        help="Use Gemini API instead of stubs"
    )

    args = parser.parse_args()

    if args.scenario != "baseline":
        print(f"Unknown scenario: {args.scenario}. Only 'baseline' is supported.")
        sys.exit(1)

    trace = asyncio.run(run_baseline(use_gemini=args.gemini))
    print_trace(trace, format=args.format)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(serialize_trace(trace), f, indent=2)
        print(f"✅ Trace written to {args.output}")


if __name__ == "__main__":
    main()
