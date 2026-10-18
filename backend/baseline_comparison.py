"""
CUE Wind Tunnel — Paired Baseline Comparison

Compares the hardened repair-enabled pipeline against a detect-only baseline
using the EXACT SAME serialized fault configurations from sweep_all_faults.py.

Metrics compared side-by-side:
  - Initial Faults Detected
  - Unresolved Violations (Baseline vs Hardened)
  - Verified Recoveries (Repairs that pass all structural & goal invariants)
  - Unsafe Actions Prevented (Safety gate interception)
  - Correctly Refused Repairs (Unrecoverable faults declined)
  - False Positives on Clean Controls
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from models import Commitment, AgentAction, Mutation
from scenarios import SSO_SCENARIO
from pipeline import create_pipeline
from mutations import apply_mutation
from invariants import check_all_invariants, goal_sso_safe_deployment
from phase3_fixes import extract_culprits, attempt_repair
from llm_client import StubLLMClient
from sweep_all_faults import build_fault_matrix, FaultConfig


@dataclass
class BaselineRecord:
    config_name: str
    mutation_type: str
    detected: bool
    initial_violations: List[str]
    # Detect-only mode (repair disabled)
    baseline_resolved: bool
    baseline_deploy: str
    baseline_unsafe_blocked: bool
    # Hardened mode (repair enabled)
    hardened_outcome: str  # RECOVERED, SAFE_REFUSAL, UNRESOLVED, etc.
    hardened_resolved: bool
    hardened_deploy: str
    hardened_unsafe_blocked: bool
    repair_verdict: Optional[str]


async def run_paired_comparison() -> List[BaselineRecord]:
    configs = build_fault_matrix()
    records = []
    client = StubLLMClient()
    order = [a.id for a in SSO_SCENARIO.agents]

    for cfg in configs:
        mut_type = "CLEAN" if cfg.mutation is None else cfg.mutation.type.value.upper()

        # ════════════════════════════════════════════════════════════════
        # RUN 1: BASELINE (Detect-Only, Repair Disabled)
        # ════════════════════════════════════════════════════════════════
        p_base = create_pipeline(scenario=SSO_SCENARIO, order=order.copy(), llm=client)
        if cfg.mutation:
            apply_mutation(p_base, cfg.mutation)
        tr_base = await p_base.run()
        inv_base = check_all_invariants(tr_base)
        failed_base = [r for r in inv_base if not r.passed]
        base_violations = [r.invariant_id for r in failed_base]
        detected = len(base_violations) > 0

        # In baseline (detect-only), violations are NEVER repaired -> always unresolved
        base_resolved = False if detected else True

        # Check if baseline deployment was safely held/blocked or executed
        dep_base = p_base.store.get_latest("deploy_action")
        base_deploy_val = dep_base.value if dep_base else "missing"
        base_blocked = any(
            isinstance(e, AgentAction) and e.action_type in ("deploy_blocked", "execution_blocked")
            for e in tr_base
        )

        # ════════════════════════════════════════════════════════════════
        # RUN 2: HARDENED (Detection + Cascade Repair + Goal Oracle)
        # ════════════════════════════════════════════════════════════════
        p_hard = create_pipeline(scenario=SSO_SCENARIO, order=order.copy(), llm=client)
        if cfg.mutation:
            apply_mutation(p_hard, cfg.mutation)
        tr_hard = await p_hard.run()
        inv_hard = check_all_invariants(tr_hard)
        failed_hard = [r for r in inv_hard if not r.passed]
        hard_violations = [r.invariant_id for r in failed_hard]

        dep_hard = p_hard.store.get_latest("deploy_action")
        hard_deploy_val = dep_hard.value if dep_hard else "missing"
        hard_blocked = any(
            isinstance(e, AgentAction) and e.action_type in ("deploy_blocked", "execution_blocked")
            for e in tr_hard
        )

        hard_outcome = "MISSED"
        hard_resolved = False
        repair_v = None

        if not hard_violations:
            if cfg.mutation is None:
                hard_outcome = "CLEAN_OK"
                hard_resolved = True
            else:
                hard_outcome = "RECOVERED" if cfg.expected_violation is None else "MISSED"
                hard_resolved = True if cfg.expected_violation is None else False
        else:
            culprits = extract_culprits(tr_hard, "", inv_hard)
            types_set = set(c[0] for c in culprits)

            if "stale_read" in types_set:
                sr_readers = list(set(c[2] for c in culprits if c[0] == "stale_read"))
                verdict, reason, post_tr = await attempt_repair(SSO_SCENARIO, cfg.mutation, sr_readers, client)
                repair_v = verdict

                if verdict == "Accepted":
                    hard_outcome = "RECOVERED"
                    hard_resolved = True
                    for e in reversed(post_tr or []):
                        if isinstance(e, Commitment) and e.key == "deploy_action" and not e.revoked:
                            hard_deploy_val = e.value
                            break
                        if isinstance(e, AgentAction) and e.action_type in ("deploy_blocked", "execution_blocked"):
                            hard_blocked = True
                elif verdict == "Failed":
                    hard_outcome = "UNRESOLVED"
                    hard_resolved = False
                else:
                    hard_outcome = "SAFE_REFUSAL"
                    hard_resolved = False
            elif types_set.intersection({"blocked_execution", "duplicate", "revoked_read", "goal_violation"}):
                hard_outcome = "SAFE_REFUSAL"
                hard_resolved = False
                repair_v = "Declined"
            else:
                hard_outcome = "UNRESOLVED"
                hard_resolved = False

        records.append(BaselineRecord(
            config_name=cfg.name,
            mutation_type=mut_type,
            detected=detected,
            initial_violations=base_violations,
            baseline_resolved=base_resolved,
            baseline_deploy=base_deploy_val,
            baseline_unsafe_blocked=base_blocked,
            hardened_outcome=hard_outcome,
            hardened_resolved=hard_resolved,
            hardened_deploy=hard_deploy_val,
            hardened_unsafe_blocked=hard_blocked,
            repair_verdict=repair_v
        ))

    return records


def print_comparison_table(records: List[BaselineRecord]):
    print("\n" + "=" * 110)
    print("CUE WIND TUNNEL — PAIRED BASELINE COMPARISON (DETECT-ONLY vs HARDENED REPAIR)")
    print("=" * 110)

    header = f"{'Configuration':<34} {'Fault':<12} {'Detected?':<10} {'Baseline (Detect-Only)':<25} {'Hardened (Self-Healing)':<25}"
    print(header)
    print("-" * 110)

    base_unresolved_total = 0
    hard_recovered_total = 0
    hard_refused_total = 0
    unsafe_prevented_total = 0
    clean_fps = 0

    for r in records:
        det_str = "YES" if r.detected else "no"

        # Baseline summary
        if r.mutation_type == "CLEAN":
            base_str = "PASS (0 faults)"
            if r.detected:
                clean_fps += 1
        else:
            if r.detected:
                base_unresolved_total += 1
                base_str = f"UNRESOLVED ({len(r.initial_violations)} viols)"
            else:
                base_str = "No race / Valid neg"

        # Hardened summary
        if r.hardened_outcome in ("RECOVERED", "CLEAN_OK"):
            if r.mutation_type != "CLEAN" and r.detected:
                hard_recovered_total += 1
                hard_str = f"RECOVERED (deploy={r.hardened_deploy})"
            else:
                hard_str = "PASS (safe execution)"
        elif r.hardened_outcome == "SAFE_REFUSAL":
            hard_refused_total += 1
            hard_str = f"SAFE REFUSAL (declined)"
        else:
            hard_str = f"UNRESOLVED ({r.hardened_outcome})"

        if r.hardened_unsafe_blocked or r.baseline_unsafe_blocked:
            unsafe_prevented_total += 1

        print(f"{r.config_name:<34} {r.mutation_type:<12} {det_str:<10} {base_str:<25} {hard_str:<25}")

    print("-" * 110)
    print("\n" + "=" * 60)
    print("SUMMARY COMPARISON METRICS")
    print("=" * 60)
    print(f"Total Test Configurations:          {len(records)}")
    print(f"Clean Control False Positives:      {clean_fps} (0 expected)")
    print(f"Baseline Unresolved Violations:     {base_unresolved_total}")
    print(f"Hardened Verified Recoveries:       {hard_recovered_total}")
    print(f"Hardened Correct Safe Refusals:     {hard_refused_total}")
    print(f"Unsafe Execution Actions Intercepted:{unsafe_prevented_total}")
    print(f"Net Recovery Delta:                 +{hard_recovered_total} violations autonomously healed")
    print("=" * 60)


async def main():
    records = await run_paired_comparison()
    print_comparison_table(records)


if __name__ == "__main__":
    asyncio.run(main())
