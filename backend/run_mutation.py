"""
CUE Wind Tunnel — Run Mutation CLI

Usage:
    python run_mutation.py --type revoke --target_key auth_protocol
    python run_mutation.py --type reorder --target_agent deployment --params '{"swap_with": "qa"}'
    python run_mutation.py --type content_flip --target_key auth_protocol --params '{"from_value":"oauth","to_value":"saml","flip_after":"engineering"}'
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys

from models import Mutation, MutationType
from mutations import run_with_mutation
from run_pipeline import print_trace
from check_invariants import print_results


def main():
    parser = argparse.ArgumentParser(description="CUE Wind Tunnel — Mutation Runner")
    parser.add_argument(
        "--type", required=True,
        choices=[m.value for m in MutationType],
        help="Mutation type"
    )
    parser.add_argument("--target_agent", default="", help="Target agent ID")
    parser.add_argument("--target_key", default="", help="Target commitment key")
    parser.add_argument(
        "--params", default="{}",
        help="JSON params for the mutation"
    )
    parser.add_argument(
        "--format", default="pretty", choices=["pretty", "json"],
        help="Output format"
    )
    args = parser.parse_args()

    params = json.loads(args.params)

    # Set sensible defaults based on mutation type
    target_agent = args.target_agent
    target_key = args.target_key

    if args.type == "revoke" and not params.get("revoke_after"):
        params["revoke_after"] = target_agent or "engineering"

    if args.type == "content_flip":
        if "from_value" not in params:
            params["from_value"] = "oauth"
        if "to_value" not in params:
            params["to_value"] = "saml"
        if "flip_after" not in params:
            params["flip_after"] = target_agent or "engineering"

    if args.type == "reorder" and not target_agent:
        target_agent = "deployment"
        if "swap_with" not in params:
            params["swap_with"] = "qa"

    mutation = Mutation(
        type=MutationType(args.type),
        target_agent=target_agent,
        target_key=target_key,
        params=params,
    )

    print(f"\n🧬 Applying mutation: {mutation.describe()}")
    print(f"   Type: {mutation.type.value}")
    print(f"   Target: {mutation.target_agent} / {mutation.target_key}")
    print(f"   Params: {json.dumps(mutation.params)}")

    result = asyncio.run(run_with_mutation(mutation))

    print_trace(result.trace, format=args.format)
    all_pass = print_results(result.invariant_results)

    if result.violated_invariants:
        print(f"\n🎯 Mutation successfully triggered {len(result.violated_invariants)} violation(s)!")
        for v in result.violated_invariants:
            print(f"   → {v}")
    else:
        print("\n✅ No invariant violations found with this mutation.")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
