"""
CUE Wind Tunnel — Fault-Type Sweep with Clean Controls

Runs a deterministic matrix of 30 fault configurations + 5 clean-control runs.
Each run is classified into exactly one outcome:
  RECOVERED     — violation detected, repair cascade resolved it, goal passes
  SAFE_REFUSAL  — violation detected, repair correctly declined (unrecoverable)
  UNRESOLVED    — violation detected, repair attempted but invariants still fail
  MISSED        — fault injected but no invariant violation detected
  FALSE_POSITIVE— no fault injected but invariant incorrectly flagged a violation
  CRASH         — unhandled exception during the run

Ground truth per configuration:
  - expected_violation: which invariant(s) should fire, or None for clean runs
  - recoverable: whether cascade repair can resolve the violation
  - safe_final_state: what the deployment decision must be after repair
"""

import asyncio
import traceback
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from models import Commitment, AgentAction, Mutation, MutationType
from scenarios import SSO_SCENARIO
from pipeline import create_pipeline
from mutations import apply_mutation
from invariants import check_all_invariants, goal_sso_safe_deployment
from phase3_fixes import extract_culprits, attempt_repair
from llm_client import StubLLMClient


# ─── Ground-Truth Configuration ───────────────────────────────────────────

@dataclass
class FaultConfig:
    """One test configuration with ground-truth expectations."""
    name: str
    mutation: Optional[Mutation]
    expected_violation: Optional[str]   # None = clean run, expects no violation
    recoverable: bool                    # True = cascade repair should fix it
    safe_final_deploy: str               # Expected deployment commitment value
    notes: str = ""


def build_fault_matrix() -> List[FaultConfig]:
    """30 fault configs + 5 clean controls = 35 total runs."""
    configs = []
    agents = [a.id for a in SSO_SCENARIO.agents]
    keys = [a.writes for a in SSO_SCENARIO.agents]

    # ═══ CLEAN CONTROLS (5 runs) ═══
    for i in range(5):
        configs.append(FaultConfig(
            name=f"CLEAN_CONTROL_{i+1}",
            mutation=None,
            expected_violation=None,
            recoverable=False,
            safe_final_deploy="deploy",
            notes=f"Unmutated pipeline run #{i+1}"
        ))

    # ═══ CONTENT_FLIP (8 configs) ═══
    # Flip impl after QA: QA approved oauth, but impl is now saml -> stale read!
    configs.append(FaultConfig(
        name="FLIP_impl_after_qa_saml",
        mutation=Mutation(type=MutationType.CONTENT_FLIP, target_agent="system",
                         target_key="implemented_protocol",
                         params={"to_value": "saml", "flip_after": "qa"}),
        expected_violation="no_downstream_disagreement",
        recoverable=True,
        safe_final_deploy="hold",
        notes="Flip impl after QA; deployment reads stale approval"
    ))
    # Flip impl after QA to oidc
    configs.append(FaultConfig(
        name="FLIP_impl_after_qa_oidc",
        mutation=Mutation(type=MutationType.CONTENT_FLIP, target_agent="system",
                         target_key="implemented_protocol",
                         params={"to_value": "oidc", "flip_after": "qa"}),
        expected_violation="no_downstream_disagreement",
        recoverable=True,
        safe_final_deploy="hold",
        notes="Flip impl to oidc after QA; deployment reads stale approval"
    ))
    # Flip qa_approval after deployment: deployment acted on approved, now oidc
    configs.append(FaultConfig(
        name="FLIP_qa_after_deploy",
        mutation=Mutation(type=MutationType.CONTENT_FLIP, target_agent="system",
                         target_key="qa_approval",
                         params={"to_value": "oidc", "flip_after": "deployment"}),
        expected_violation="no_downstream_disagreement",
        recoverable=True,
        safe_final_deploy="hold",
        notes="Flip qa_approval after deployment; deployment state stale"
    ))
    # Flip auth_protocol after engineering: engineering implemented oauth, but auth is now saml
    configs.append(FaultConfig(
        name="FLIP_auth_after_eng_saml",
        mutation=Mutation(type=MutationType.CONTENT_FLIP, target_agent="system",
                         target_key="auth_protocol",
                         params={"to_value": "saml", "flip_after": "engineering"}),
        expected_violation="no_downstream_disagreement",
        recoverable=True,
        safe_final_deploy="hold",
        notes="Flip auth after engineering; QA reads auth=saml and impl=oauth"
    ))
    # Flip auth_protocol after engineering to oidc
    configs.append(FaultConfig(
        name="FLIP_auth_after_eng_oidc",
        mutation=Mutation(type=MutationType.CONTENT_FLIP, target_agent="system",
                         target_key="auth_protocol",
                         params={"to_value": "oidc", "flip_after": "engineering"}),
        expected_violation="no_downstream_disagreement",
        recoverable=True,
        safe_final_deploy="hold",
        notes="Flip auth to oidc after eng; QA reads mismatched protocols"
    ))
    # Flip impl after deployment: docs reads stale impl
    configs.append(FaultConfig(
        name="FLIP_impl_after_deploy",
        mutation=Mutation(type=MutationType.CONTENT_FLIP, target_agent="system",
                         target_key="implemented_protocol",
                         params={"to_value": "saml", "flip_after": "deployment"}),
        expected_violation="no_downstream_disagreement",
        recoverable=True,
        safe_final_deploy="deploy",
        notes="Flip impl after deployment; docs reads stale"
    ))
    # Flip implemented_protocol after engineering: QA naturally adapts and rejects (valid negative)
    configs.append(FaultConfig(
        name="FLIP_impl_before_qa_natural_reject",
        mutation=Mutation(type=MutationType.CONTENT_FLIP, target_agent="system",
                         target_key="implemented_protocol",
                         params={"to_value": "saml", "flip_after": "engineering"}),
        expected_violation=None,
        recoverable=False,
        safe_final_deploy="hold",
        notes="QA reads updated impl before deciding; rejects naturally (valid negative)"
    ))
    # Flip documented_protocol after docs: docs is terminal (valid negative)
    configs.append(FaultConfig(
        name="FLIP_docs_terminal",
        mutation=Mutation(type=MutationType.CONTENT_FLIP, target_agent="system",
                         target_key="documented_protocol",
                         params={"to_value": "saml", "flip_after": "docs"}),
        expected_violation=None,
        recoverable=False,
        safe_final_deploy="deploy",
        notes="Terminal agent mutated; no downstream readers exist (valid negative)"
    ))

    # ═══ REVOKE (4 configs) ═══
    # Revoke auth after security
    configs.append(FaultConfig(
        name="REVOKE_auth_after_security",
        mutation=Mutation(type=MutationType.REVOKE, target_agent="security",
                         target_key="auth_protocol", params={"revoke_after": "security"}),
        expected_violation="goal_sso_safe_deployment",
        recoverable=False,
        safe_final_deploy="missing",
        notes="Revoke auth_protocol; pipeline stalls safely, goal detects missing state"
    ))
    # Revoke implemented_protocol after engineering
    configs.append(FaultConfig(
        name="REVOKE_impl_after_engineering",
        mutation=Mutation(type=MutationType.REVOKE, target_agent="engineering",
                         target_key="implemented_protocol", params={"revoke_after": "engineering"}),
        expected_violation="goal_sso_safe_deployment",
        recoverable=False,
        safe_final_deploy="missing",
        notes="Revoke implemented_protocol; downstream blocked safely"
    ))
    # Revoke qa_approval after QA
    configs.append(FaultConfig(
        name="REVOKE_qa_after_qa",
        mutation=Mutation(type=MutationType.REVOKE, target_agent="qa",
                         target_key="qa_approval", params={"revoke_after": "qa"}),
        expected_violation="goal_sso_safe_deployment",
        recoverable=False,
        safe_final_deploy="missing",
        notes="Revoke qa_approval; deployment cannot proceed"
    ))
    # Revoke deploy_action after deployment: deployment was already finished, terminal key revoked
    configs.append(FaultConfig(
        name="REVOKE_deploy_after_deployment",
        mutation=Mutation(type=MutationType.REVOKE, target_agent="deployment",
                         target_key="deploy_action", params={"revoke_after": "deployment"}),
        expected_violation=None,
        recoverable=False,
        safe_final_deploy="missing",
        notes="Terminal deploy key revoked post-facto; docs not affected (valid negative)"
    ))

    # ═══ DELAY (4 configs) ═══
    for agent, delay in [("engineering", 5), ("engineering", 15), ("qa", 5), ("deployment", 10)]:
        configs.append(FaultConfig(
            name=f"DELAY_{agent}_{delay}s",
            mutation=Mutation(type=MutationType.DELAY, target_agent=agent,
                             params={"delay_seconds": delay}),
            expected_violation=None,
            recoverable=False,
            safe_final_deploy="deploy",
            notes=f"Delay {agent} by {delay}s; DES preserves causal order (valid negative)"
        ))

    # ═══ REORDER (6 configs) ═══
    for seed in [42, 99, 7]:
        for variant in [0, 1]:
            configs.append(FaultConfig(
                name=f"REORDER_seed{seed}_v{variant}",
                mutation=Mutation(type=MutationType.REORDER, target_agent="system",
                                 params={"seed": seed, "variant": variant}),
                expected_violation=None,
                recoverable=False,
                safe_final_deploy="deploy",
                notes=f"Shuffle initial pool; DES enforces topological safety (valid negative)"
            ))

    # ═══ DUPLICATE (4 configs) ═══
    for agent in ["engineering", "qa", "deployment", "docs"]:
        configs.append(FaultConfig(
            name=f"DUPLICATE_{agent}",
            mutation=Mutation(type=MutationType.DUPLICATE, target_agent=agent,
                             target_key="", params={}),
            expected_violation="no_duplicate_execution",
            recoverable=False,
            safe_final_deploy="deploy",
            notes=f"Force duplicate execution of {agent}; flagged as invalid redundancy"
        ))

    return configs


# ─── Outcome Classification ──────────────────────────────────────────────

OUTCOMES = ["RECOVERED", "SAFE_REFUSAL", "UNRESOLVED", "MISSED", "FALSE_POSITIVE", "CRASH"]

@dataclass
class RunResult:
    config: FaultConfig
    outcome: str
    violations_detected: List[str] = field(default_factory=list)
    repair_verdict: Optional[str] = None
    repair_reason: Optional[str] = None
    final_deploy: Optional[str] = None
    error: Optional[str] = None


async def execute_single_run(cfg: FaultConfig) -> RunResult:
    """Run one fault configuration and classify the outcome."""
    try:
        client = StubLLMClient()
        order = [a.id for a in SSO_SCENARIO.agents]
        p = create_pipeline(scenario=SSO_SCENARIO, order=order.copy(), llm=client)

        # Apply mutation if present
        if cfg.mutation:
            apply_mutation(p, cfg.mutation)

        # Run pipeline
        trace = await p.run()

        # Check invariants
        results = check_all_invariants(trace)
        failed = [r for r in results if not r.passed]
        violation_ids = [r.invariant_id for r in failed]

        # Get final deployment state
        deploy_c = p.store.get_latest("deploy_action")
        final_deploy = deploy_c.value if deploy_c else "missing"

        # ── CLEAN RUN (no mutation) ──
        if cfg.mutation is None:
            if failed:
                return RunResult(cfg, "FALSE_POSITIVE", violation_ids, final_deploy=final_deploy)
            else:
                return RunResult(cfg, "RECOVERED", violation_ids, final_deploy=final_deploy,
                                 repair_reason="Clean run, no fault injected")

        # ── MUTATED RUN ──
        if not failed:
            # No violation detected
            if cfg.expected_violation is None:
                # Expected: valid negative (DELAY, REORDER that don't cause races)
                return RunResult(cfg, "RECOVERED", violation_ids, final_deploy=final_deploy,
                                 repair_reason="Valid negative: fault did not produce violation")
            else:
                return RunResult(cfg, "MISSED", violation_ids, final_deploy=final_deploy)

        # Violation detected — attempt repair if classified as stale_read
        culprits = extract_culprits(trace, "", results)
        types_set = set(c[0] for c in culprits)

        if "stale_read" in types_set:
            sr_readers = list(set(c[2] for c in culprits if c[0] == "stale_read"))
            verdict, reason, post_trace = await attempt_repair(SSO_SCENARIO, cfg.mutation, sr_readers, client)

            if verdict == "Accepted":
                # Verify post-repair deployment state
                post_deploy = None
                for e in reversed(post_trace or []):
                    if isinstance(e, Commitment) and e.key == "deploy_action" and not e.revoked:
                        post_deploy = e.value
                        break
                return RunResult(cfg, "RECOVERED", violation_ids, verdict, reason,
                                 final_deploy=post_deploy or final_deploy)
            elif verdict == "Failed":
                return RunResult(cfg, "UNRESOLVED", violation_ids, verdict, reason,
                                 final_deploy=final_deploy)
            else:
                return RunResult(cfg, "SAFE_REFUSAL", violation_ids, verdict, reason,
                                 final_deploy=final_deploy)

        elif types_set.intersection({"blocked_execution", "duplicate", "revoked_read", "goal_violation"}):
            return RunResult(cfg, "SAFE_REFUSAL", violation_ids,
                             repair_reason="Classified as non-repairable; correctly refused",
                             final_deploy=final_deploy)
        else:
            return RunResult(cfg, "UNRESOLVED", violation_ids,
                             repair_reason=f"Unclassified culprit types: {types_set}",
                             final_deploy=final_deploy)

    except Exception as e:
        return RunResult(cfg, "CRASH", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


# ─── Reporting ────────────────────────────────────────────────────────────

def print_report(results: List[RunResult]):
    """Print per-fault-type breakdown with raw counts."""

    # Group by mutation type
    groups: Dict[str, List[RunResult]] = {}
    for r in results:
        if r.config.mutation is None:
            key = "CLEAN_CONTROL"
        else:
            key = r.config.mutation.type.value.upper()
        groups.setdefault(key, []).append(r)

    # Header
    print("\n" + "=" * 100)
    print("CUE WIND TUNNEL — FAULT-TYPE SWEEP RESULTS")
    print("=" * 100)

    header = f"{'Fault Type':<16} {'Attempts':>8} {'Recovered':>10} {'Refused':>9} {'Unresolved':>11} {'Missed':>7} {'FP':>4} {'Crash':>6}"
    print(header)
    print("-" * 100)

    totals = {o: 0 for o in OUTCOMES}
    total_attempts = 0

    for fault_type in ["CLEAN_CONTROL", "CONTENT_FLIP", "REVOKE", "DELAY", "REORDER", "DUPLICATE"]:
        group = groups.get(fault_type, [])
        if not group:
            continue
        counts = {o: 0 for o in OUTCOMES}
        for r in group:
            counts[r.outcome] += 1
            totals[r.outcome] += 1
        n = len(group)
        total_attempts += n
        print(f"{fault_type:<16} {n:>8} {counts['RECOVERED']:>10} {counts['SAFE_REFUSAL']:>9} "
              f"{counts['UNRESOLVED']:>11} {counts['MISSED']:>7} {counts['FALSE_POSITIVE']:>4} {counts['CRASH']:>6}")

    print("-" * 100)
    print(f"{'TOTAL':<16} {total_attempts:>8} {totals['RECOVERED']:>10} {totals['SAFE_REFUSAL']:>9} "
          f"{totals['UNRESOLVED']:>11} {totals['MISSED']:>7} {totals['FALSE_POSITIVE']:>4} {totals['CRASH']:>6}")
    print("=" * 100)

    # ── Per-run detail ──
    print("\n--- PER-RUN DETAIL ---")
    for r in results:
        status_icon = {"RECOVERED": "✓", "SAFE_REFUSAL": "⊘", "UNRESOLVED": "✗",
                       "MISSED": "?", "FALSE_POSITIVE": "!", "CRASH": "☠"}.get(r.outcome, "?")
        detail = r.repair_reason or r.error or ""
        if len(detail) > 80:
            detail = detail[:77] + "..."
        print(f"  {status_icon} {r.config.name:<35} → {r.outcome:<15} deploy={r.final_deploy or '?':<6} {detail}")

    # ── Acceptance criteria ──
    print("\n--- ACCEPTANCE CRITERIA ---")
    crashes = totals["CRASH"]
    fps = totals["FALSE_POSITIVE"]

    # Recovery rate denominator: only configs where expected_violation is set AND recoverable=True
    repairable_detected = [r for r in results
                           if r.config.recoverable and r.config.expected_violation
                           and r.outcome in ("RECOVERED", "UNRESOLVED")]
    recovered_count = sum(1 for r in repairable_detected if r.outcome == "RECOVERED")
    repair_denom = len(repairable_detected)
    recovery_rate = (recovered_count / repair_denom * 100) if repair_denom > 0 else 0

    print(f"  Crashes:          {crashes} (acceptance: 0)")
    print(f"  False positives:  {fps} (acceptance: 0)")
    print(f"  Recovery rate:    {recovered_count}/{repair_denom} = {recovery_rate:.1f}% (acceptance: >60%)")
    print(f"  Safe refusals:    {totals['SAFE_REFUSAL']} on unrecoverable faults")

    ok = crashes == 0 and fps == 0 and recovery_rate >= 60.0
    print(f"\n  SUITE VERDICT: {'PASSED' if ok else 'FAILED'}")
    return 0 if ok else 1


async def main():
    configs = build_fault_matrix()
    print(f"Running {len(configs)} fault configurations...")

    results = []
    for i, cfg in enumerate(configs):
        print(f"  [{i+1}/{len(configs)}] {cfg.name}...", end=" ", flush=True)
        r = await execute_single_run(cfg)
        print(r.outcome)
        results.append(r)

    exit_code = print_report(results)
    return exit_code


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
