"""
Phase 3 Fixes — All 5 items in one script.
1. Structured Gemini summary (facts only)
2. Realistic values + narration order (reads before writes) + verdict reason
3. Sweep diagnostics (attempts, crashes, per-run params, split decline reasons)
4. REVOKE violation explanation (code path)
5. QA stub output when protocols mismatch
"""
import asyncio
import sys
import re
import random
import traceback

from scenarios import SSO_SCENARIO
from search import adversarial_search
from shrinker import shrink
from llm_client import get_llm_client, GeminiLLMClient
from mutations import apply_mutation, Mutation, MutationType, random_mutation
from pipeline import create_pipeline, CommitmentStore
from invariants import check_all_invariants


# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────

def build_commit_map(trace):
    """Map commitment IDs to (key, version, value)."""
    m = {}
    for e in trace:
        if not hasattr(e, 'action_type') and hasattr(e, 'key'):
            m[e.id] = (e.key, e.version, e.value)
    return m


def narrate_trace(trace, violation_text, verdict, verdict_reason):
    """Construct a readable narration: reads before writes, key names resolved."""
    cmap = build_commit_map(trace)
    lines = []

    for e in trace:
        if hasattr(e, 'action_type'):
            if e.action_type == "content_flip":
                cid = e.produced_commitment_id
                k, v, val = cmap.get(cid, ("?", "?", "?"))
                lines.append(f"  [Mutation] System flipped {k} to '{val}' (now v{v}).")
            elif e.action_type.startswith("delay"):
                lines.append(f"  [Mutation] System delayed {e.agent_id}.")
            else:
                # agent execution — reads first, then writes
                reads = []
                for cid in e.reads:
                    k, v, val = cmap.get(cid, ("?", "?", "?"))
                    reads.append(f"{k}='{val}' v{v}")
                read_str = ", ".join(reads) if reads else "(no reads)"
                action_line = f"  [{e.agent_id}] read {read_str}"

                # find write produced by this action
                if e.produced_commitment_id:
                    k, v, val = cmap.get(e.produced_commitment_id, ("?", "?", "?"))
                    action_line += f" → wrote {k}='{val}' (v{v})"
                lines.append(action_line)
        else:
            pass  # commitments are reported inline via produced_commitment_id

    lines.append(f"")
    lines.append(f"  [Broken Invariant] {violation_text}")
    lines.append(f"  [Verdict] Repair {verdict.lower()} because {verdict_reason}.")
    return "\n".join(lines)


def extract_culprits(trace, violation_text, invariant_results):
    """Returns a list of tuples: (violation_type, change_source, stale_reader, invariant_id)."""
    culprits = []
    
    for r in invariant_results:
        if r.passed:
            continue
            
        if r.invariant_id == "no_duplicate_execution":
            match = re.search(r"^(\w+) executed", r.reason)
            agent = match.group(1) if match else "unknown"
            culprits.append(("duplicate", agent, "N/A", r.invariant_id))
            
        elif r.invariant_id == "no_blocked_executions":
            match = re.search(r"^(\w+) was blocked", r.reason)
            agent = match.group(1) if match else "unknown"
            culprits.append(("blocked_execution", agent, "N/A", r.invariant_id))
        elif "based on a stale read of" in r.reason:
            # Can be multiple violations joined by |
            for part in r.reason.split(" | "):
                match = re.search(r"(.+?)'s active", part.strip())
                if match:
                    stale_reader = match.group(1)
                    change_source = "unknown"
                    dep_match = re.search(r"stale read of '(.+?)' \(v(\d+)", part)
                    if dep_match:
                        dep_key = dep_match.group(1)
                        dep_v = int(dep_match.group(2))
                        for e in trace:
                            if not hasattr(e, 'action_type') and hasattr(e, 'key') and e.key == dep_key and e.version == dep_v:
                                change_source = e.agent_id
                                break
                    culprits.append(("stale_read", change_source, stale_reader, r.invariant_id))
            
        elif r.invariant_id == "no_deploy_without_current_approval":
            culprits.append(("stale_read", "qa", "deployment", r.invariant_id))
            
        elif r.invariant_id == "goal_sso_safe_deployment":
            culprits.append(("goal_violation", "system", "deployment", r.invariant_id))
            
        elif "revoked" in r.reason.lower() or "Deployment executed" in r.reason:
            culprits.append(("revoked_read", "system", "N/A", r.invariant_id))
            
        else:
            culprits.append(("other", "unknown", "unknown", r.invariant_id))

    return culprits


def get_downstream(scenario, stale_reader):
    order = [a.id for a in scenario.agents]
    if stale_reader not in order:
        return []
    targets = [stale_reader]
    agents = {a.id: a for a in scenario.agents}
    keys = {agents[stale_reader].writes}
    idx = order.index(stale_reader)
    for later in order[idx + 1:]:
        a = agents[later]
        if any(rd in keys for rd in a.reads):
            targets.append(later)
            keys.add(a.writes)
    return targets


async def attempt_repair(scenario, mutation, stale_readers: list[str], client):
    """Re-run stale_readers + downstream. Returns (verdict, reason, post_trace)."""
    order = [a.id for a in scenario.agents]
    TargetSet = set()
    if isinstance(stale_readers, str):
        stale_readers = [stale_readers]
        
    for sr in stale_readers:
        TargetSet.add(sr)
        TargetSet.update(get_downstream(scenario, sr))
        
    if not TargetSet:
        return "Declined", "no downstream targets found", None
        
    targets = list(TargetSet)
    order_idx = {name: i for i, name in enumerate(order)}
    targets.sort(key=lambda x: order_idx.get(x, 100))

    # Run the raw original pipeline (with the mutation injected)
    p = create_pipeline(scenario=scenario, order=order.copy(), llm=client)
    apply_mutation(p, mutation)
    
    # Run the original trace
    tr = await p.run()
    
    # Execute cascade repair
    await p.run_cascade(targets)
    
    # Evaluate post-repair state against all invariants (including independent goal)
    res = check_all_invariants(p.trace)
    if all(r.passed for r in res):
        return "Accepted", f"cascade re-ran {','.join(targets)} and all invariants (including goal) now pass", p.trace
    else:
        failed = [r for r in res if not r.passed]
        reasons = "; ".join(f"{r.invariant_id}: {r.reason}" for r in failed[:2])
        return "Failed", f"cascade re-ran {','.join(targets)} but invariants failed ({reasons})", p.trace


# ───────────────────────────────────────────────────────────────────
# Item 5: QA stub output demo
# ───────────────────────────────────────────────────────────────────
async def demo_qa_stub():
    print("=" * 60)
    print("ITEM 5: QA STUB OUTPUT DEMO")
    print("=" * 60)
    client = get_llm_client(use_gemini=False)
    
    from models import AgentDef
    qa_def = AgentDef(id="qa", name="QA", role="quality assurance",
                      reads=["auth_protocol", "implemented_protocol"],
                      writes="qa_approval", allowed_values=["approved", "rejected"])
                      
    dep_def = AgentDef(id="deployment", name="Deployment", role="Deployer",
                       reads=["qa_approval", "implemented_protocol"],
                       writes="deploy_action", allowed_values=["deploy", "hold"])

    for proto_val in ["oauth", "saml", "oidc", "token_refresh"]:
        ctx = f"auth_protocol=oauth; implemented_protocol={proto_val}"
        qa_result = await client.generate_decision(qa_def, ctx)
        
        ctx_dep = f"qa_approval={qa_result}; implemented_protocol={proto_val}"
        dep_result = await client.generate_decision(dep_def, ctx_dep)
        print(f"  Inputs: auth=oauth, impl={proto_val}")
        print(f"  QA decision: {qa_result} | Deployment decision: {dep_result}")
        print()


# ───────────────────────────────────────────────────────────────────
# Item 4: REVOKE code path explanation
# ───────────────────────────────────────────────────────────────────
def explain_revoke():
    print("=" * 60)
    print("ITEM 4: REVOKE VIOLATION CODE PATH")
    print("=" * 60)
    print("""
  Code path for REVOKE mutation:
    1. mutations.py:apply_revoke() installs a post_hook on 'revoke_after' agent.
    2. When that agent finishes, the hook calls store.revoke(target_key).
    3. store.revoke() sets latest.revoked = True on the Commitment object.
    4. pipeline.py:get_latest() tries to find a non-revoked commitment:
         for c in reversed(versions):
             if not c.revoked:
                 return c
         return versions[-1] if versions else None    # ← fallback returns revoked!
    5. So downstream agents STILL get the revoked commitment from the fallback.
    6. invariants.py:no_downstream_disagreement() compares what agents read.
       When one agent read v1 (pre-revoke) and another reads v2 (post-revoke update),
       or when qa approved based on a protocol that was later revoked, the invariant
       fires because the trace shows a version mismatch.

  Why REVOKE now causes violations (it didn't before):
    - Earlier runs used StubLLMClient which always returns 'approved' regardless
      of context. The honest QA stub now returns 'approved_{protocol_value}',
      which changes the qa_approval fingerprint. When the revoked key is
      'implemented_protocol' or 'qa_approval', downstream agents see inconsistent
      state that the no_downstream_disagreement invariant catches.
    - Additionally, when target_key='qa_approval' and revoke_after is an earlier
      agent, deployment reads a revoked approval, triggering no_action_on_revoked.
""")


# ───────────────────────────────────────────────────────────────────
# Items 1+2: 20-seed table with fixed narration + structured Gemini
# ───────────────────────────────────────────────────────────────────
async def run_20_seed_table():
    print("=" * 60)
    print("ITEMS 1+2: 20-SEED TABLE (REALISTIC VALUES + HONEST QA)")
    print("=" * 60)
    client = get_llm_client(use_gemini=False)
    order = [a.id for a in SSO_SCENARIO.agents]
    seeds = list(range(1, 21))
    all_runs = {1: {}, 2: {}}

    for run_id in [1, 2]:
        print(f"\n  Generating Run {run_id}...")
        for s in seeds:
            best = await adversarial_search(SSO_SCENARIO, budget=20, seed=s)
            if not best:
                all_runs[run_id][s] = {
                    "vtype": "none",
                    "csrc": "N/A",
                    "sreader": "N/A",
                    "inv_id": "N/A",
                    "targets": "None",
                    "verdict": "Accepted",
                    "reason": "0 violations found by adversarial search"
                }
                continue
            
            shrunk = await shrink(best, SSO_SCENARIO)

            p = create_pipeline(scenario=SSO_SCENARIO, order=order.copy(), llm=client)
            apply_mutation(p, shrunk.mutation)
            tr = await p.run()
            res = check_all_invariants(tr)
            
            culprits = extract_culprits(tr, shrunk.violation, res)

            verdict = ""
            reason = ""
            targets = []

            # Documented repair policy:
            # 1. If ANY violation is a duplicate, we decline immediately.
            # 2. If it's a stale read (and no duplicate), we attempt cascade repair.
            # 3. Else, we decline.
            
            has_dup = any(c[0] == "duplicate" for c in culprits)
            has_blocked = any(c[0] == "blocked_execution" for c in culprits)
            
            primary_vtype = ",".join(sorted(set(c[0] for c in culprits)))
            primary_csrc = ",".join(sorted(set(c[1] for c in culprits if c[1] != "N/A")))
            primary_sreader = ",".join(sorted(set(c[2] for c in culprits if c[2] != "N/A")))
            all_invariants = ",".join(sorted(set(c[3] for c in culprits)))
            
            if has_dup:
                dup_source = next((c[1] for c in culprits if c[0] == "duplicate"), "unknown")
                verdict = "Declined"
                reason = f"{dup_source} executed twice with identical inputs — cannot be undone"
            elif has_blocked:
                blk_source = next((c[1] for c in culprits if c[0] == "blocked_execution"), "unknown")
                verdict = "Declined"
                reason = f"{blk_source} was blocked at action boundary safely"
            elif any(c[0] == "stale_read" for c in culprits):
                sr_readers = list(set(c[2] for c in culprits if c[0] == "stale_read"))
                targets_set = set()
                for sr in sr_readers:
                    targets_set.update(get_downstream(SSO_SCENARIO, sr))
                targets = list(targets_set)
                
                if not targets:
                    print(f"[DEBUG NO TARGETS] sr_readers: {sr_readers} culprits: {culprits}")
                    
                verdict, reason, _ = await attempt_repair(SSO_SCENARIO, shrunk.mutation, sr_readers, client)
            else:
                verdict = "Declined"
                reason = f"No repair policy covers {primary_vtype}"

            all_runs[run_id][s] = {
                "vtype": primary_vtype,
                "csrc": primary_csrc or "N/A",
                "sreader": primary_sreader or "N/A",
                "inv_id": all_invariants,
                "targets": ",".join(targets) if targets else "None",
                "verdict": verdict,
                "reason": reason,
                "trace": tr,
                "violation": shrunk.violation,
                "mutation_desc": str(shrunk.mutation),
            }

    # Comparison
    match = all(
        all_runs[1][s]["verdict"] == all_runs[2][s]["verdict"] and
        all_runs[1][s]["targets"] == all_runs[2][s]["targets"]
        for s in seeds
    )
    print(f"\n  Run 1 and Run 2 match: {match}")

    # Full table
    print(f"\n  {'Seed':<4} | {'Type':<12} | {'ChgSrc':<12} | {'StaleRdr':<10} | {'InvID':<28} | {'Targets':<15} | {'Verdict':<10} | Reason")
    print("  " + "-" * 140)
    for s in seeds:
        r = all_runs[1][s]
        print(f"  {s:<4} | {r['vtype']:<12} | {r['csrc']:<12} | {r['sreader']:<10} | {r['inv_id']:<28} | {r['targets']:<15} | {r['verdict']:<10} | {r['reason'][:60]}")

    return all_runs[1]


# ───────────────────────────────────────────────────────────────────
# Item 1: Structured Gemini summary for seeds 6 and 18
# ───────────────────────────────────────────────────────────────────
async def structured_gemini_summaries(run_data):
    print("\n" + "=" * 60)
    print("ITEM 1: TRACE NARRATION + STRUCTURED GEMINI SUMMARY")
    print("=" * 60)

    gemini = get_llm_client(use_gemini=True)

    for s in [6, 18]:
        r = run_data[s]
        narration = narrate_trace(r["trace"], r["violation"], r["verdict"], r["reason"])
        print(f"\n  --- Seed {s} Narration (Ground Truth from Trace) ---")
        print(narration)

        # Structured facts only — no free-form
        facts = (
            f"Violation type: {r['vtype']}. "
            f"Change source: {r['csrc']}. "
            f"Stale reader: {r['sreader']}. "
            f"Broken invariant: {r['inv_id']}. "
            f"Repair targets: {r['targets']}. "
            f"Verdict: {r['verdict']}. "
            f"Reason: {r['reason']}."
        )
        prompt = (
            f"Restate these facts in 3 sentences. Do NOT add anything that is not "
            f"in the facts below. Do not use words like 'unauthorized', 'security violation', "
            f"or 'acknowledging'. Only restate what is given.\n\nFacts:\n{facts}"
        )

        print(f"\n  --- Seed {s} AI Summary (gemini-3.1-flash-lite) ---")
        if hasattr(gemini, '_call_gemini'):
            summary, _ = await gemini._call_gemini([{"role": "user", "content": prompt}], max_tokens=150)
            print(f"  {summary}")
        else:
            print(f"  (No Gemini key available — stub mode)")
            print(f"  Facts: {facts}")


# ───────────────────────────────────────────────────────────────────
# Item 3: Sweep with full diagnostics
# ───────────────────────────────────────────────────────────────────
async def sweep_with_diagnostics():
    print("\n" + "=" * 60)
    print("ITEM 3: SWEEP DIAGNOSTICS (10x per MUTATION TYPE)")
    print("=" * 60)
    client = get_llm_client(use_gemini=False)
    order = [a.id for a in SSO_SCENARIO.agents]

    mutation_types = [MutationType.DELAY, MutationType.REORDER,
                      MutationType.CONTENT_FLIP, MutationType.DUPLICATE,
                      MutationType.REVOKE]

    for mtype in mutation_types:
        name = mtype.name
        print(f"\n  --- {name} ---")
        violations = 0
        attempts = 0
        crashes = 0
        crash_reasons = []
        accepted = 0
        declined_dup = 0
        declined_reasons = {}
        flip_params = []

        rng = random.Random(42 + list(MutationType).index(mtype))
        agent_ids = order

        while violations < 10 and attempts < 100:
            attempts += 1
            m = None
            realistic_values = ["saml", "oidc", "token_refresh", "legacy_auth",
                                "expired_cert", "revoked", "v2_api", "disabled"]

            if mtype == MutationType.DELAY:
                m = Mutation(type=mtype, target_agent=rng.choice(agent_ids[1:]),
                             params={"delay_seconds": rng.randint(2, 20)})
            elif mtype == MutationType.REORDER:
                a1 = rng.choice(agent_ids[:-1])
                a2 = rng.choice([x for x in agent_ids if x != a1])
                m = Mutation(type=mtype, target_agent=a1, params={"swap_with": a2})
            elif mtype == MutationType.CONTENT_FLIP:
                key = rng.choice(["auth_protocol", "implemented_protocol",
                                  "qa_approval", "deploy_action"])
                flip_after = rng.choice(agent_ids[:-1])
                to_val = rng.choice(realistic_values)
                m = Mutation(type=mtype, target_agent="system", target_key=key,
                             params={"from_value": "oauth", "to_value": to_val,
                                     "flip_after": flip_after})
            elif mtype == MutationType.DUPLICATE:
                m = Mutation(type=mtype, target_agent=rng.choice(agent_ids))
            elif mtype == MutationType.REVOKE:
                key = rng.choice(["auth_protocol", "implemented_protocol", "qa_approval"])
                rev_after = rng.choice(agent_ids[:-1])
                m = Mutation(type=mtype, target_agent="system", target_key=key,
                             params={"revoke_after": rev_after})

            try:
                p = create_pipeline(scenario=SSO_SCENARIO, order=order.copy(), llm=client)
                apply_mutation(p, m)
                tr = await p.run()
                res = check_all_invariants(tr)
            except Exception as ex:
                crashes += 1
                crash_reasons.append(f"  attempt {attempts}: {type(ex).__name__}: {str(ex)[:80]}")
                continue

            has_viol = any(not r.passed for r in res)
            if not has_viol:
                continue

            violations += 1
            culprits = extract_culprits(tr, "", res)
            
            primary_vtype = ",".join(sorted(set(c[0] for c in culprits)))
            all_invariants = ",".join(sorted(set(c[3] for c in culprits)))

            if mtype == MutationType.CONTENT_FLIP:
                flip_params.append({
                    "run": violations,
                    "key": m.target_key or m.params.get("target_key", "?"),
                    "to_value": m.params.get("to_value", "?"),
                    "flip_after": m.params.get("flip_after", "?"),
                    "violation": all_invariants,
                })

            if any(c[0] == "duplicate" for c in culprits):
                declined_dup += 1
            elif any(c[0] == "stale_read" for c in culprits):
                sr_readers = list(set(c[2] for c in culprits if c[0] == "stale_read"))
                v, reason, _ = await attempt_repair(SSO_SCENARIO, m, sr_readers, client)
                if v == "Accepted":
                    accepted += 1
                else:
                    declined_reasons[reason[:60]] = declined_reasons.get(reason[:60], 0) + 1
            else:
                reason = f"{primary_vtype}: {all_invariants}"
                declined_reasons[reason[:60]] = declined_reasons.get(reason[:60], 0) + 1

        print(f"  Attempts: {attempts} | Crashes: {crashes} | Violations found: {violations}")
        print(f"  Accepted: {accepted} | Declined (dup): {declined_dup}")
        if declined_reasons:
            print(f"  Declined reasons:")
            for reason, count in declined_reasons.items():
                print(f"    [{count}x] {reason}")
        if crash_reasons:
            print(f"  Crash details:")
            for cr in crash_reasons[:5]:
                print(f"    {cr}")

        if flip_params:
            print(f"  CONTENT_FLIP per-run params:")
            for fp in flip_params:
                print(f"    Run {fp['run']}: key={fp['key']}, to={fp['to_value']}, "
                      f"flip_after={fp['flip_after']}, violation={fp['violation']}")


# ───────────────────────────────────────────────────────────────────
async def main():
    await demo_qa_stub()
    explain_revoke()
    run_data = await run_20_seed_table()
    await structured_gemini_summaries(run_data)
    await sweep_with_diagnostics()

if __name__ == "__main__":
    asyncio.run(main())
