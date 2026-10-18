import asyncio
import io
import sys
import re
import json



from scenarios import SSO_SCENARIO
from search import adversarial_search
from shrinker import shrink
from llm_client import get_llm_client
from mutations import apply_mutation, Mutation
from pipeline import create_pipeline
from invariants import check_all_invariants

def parse_trace_for_narration(trace):
    lines = []
    for e in trace:
        if hasattr(e, 'action_type'):
            if e.action_type == "content_flip":
                lines.append(f"[System] Forced state change via mutation.")
            else:
                reads = []
                for idx in range(len(e.reads)):
                    reads.append(f"read_r{idx}_v{e.reads_versions[idx]}")
                lines.append(f"[{e.agent_id}] Executed based on {', '.join(reads)}")
        else:
            lines.append(f"[{e.agent_id}] Wrote {e.key}={e.value} (v{e.version})")
            
    return "\n".join(lines)


def extract_culprits_from_trace(trace, violation_text):
    """
    Returns (violation_type, change_source, stale_reader)
    """
    if "executed" in violation_text and "twice with the same read set" in violation_text:
        match = re.search(r"^(\w+) executed", violation_text)
        if match:
            return "duplicate", match.group(1), "N/A"
            
    elif "is based on a stale read of" in violation_text:
        stale_reader = "unknown"
        change_source = "unknown"
        
        match_reader = re.search(r"^(\w+)'s active", violation_text)
        if match_reader:
            stale_reader = match_reader.group(1)
            
        match_dep = re.search(r"read of '([^']+)' \(v(\d+) exists\)", violation_text)
        if match_dep:
            dep_key = match_dep.group(1)
            dep_v = int(match_dep.group(2))
            for e in trace:
                if not hasattr(e, 'action_type') and e.key == dep_key and e.version == dep_v:
                    change_source = e.agent_id
                    break
        return "stale_read", change_source, stale_reader
        
    return "unknown", "unknown", "unknown"

def get_downstream_agents(scenario, stale_reader):
    baseline_order = [a.id for a in scenario.agents]
    if stale_reader not in baseline_order:
        return []
        
    targets = [stale_reader]
    agent_dict = {a.id: a for a in scenario.agents}
    stale_keys = {agent_dict[stale_reader].writes}
    
    idx = baseline_order.index(stale_reader)
    for later_id in baseline_order[idx + 1:]:
        later_agent = agent_dict[later_id]
        if any(rd in stale_keys for rd in later_agent.reads):
            targets.append(later_id)
            stale_keys.add(later_agent.writes)
            
    return targets


async def run_phase2():
    client = get_llm_client(use_gemini=False)
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    
    seeds = list(range(1, 21))
    runs = {1: {}, 2: {}}
    
    for run_id in [1, 2]:
        print(f"\nGenerating Phase 2 Log Run {run_id}...")
        for s in seeds:
            best = await adversarial_search(SSO_SCENARIO, budget=20, seed=s)
            shrunk = await shrink(best, SSO_SCENARIO)
            
            # Reconstruct trace properly
            p = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
            apply_mutation(p, shrunk.mutation)
            tr = await p.run()
            res_before = check_all_invariants(tr)
            
            # Prioritize duplicates
            has_dup = False
            dup_agent = "unknown"
            for r in res_before:
                if r.invariant_id == "no_duplicate_execution" and not r.passed:
                    has_dup = True
                    # The violation reason should have the agent name in it.
                    # Or we can deduce it from the violation text
                    match = re.search(r"^(\w+) executed", r.reason)
                    if match:
                        dup_agent = match.group(1)
                    break
                    
            if has_dup:
                violation_type = "duplicate"
                change_source = dup_agent
                stale_reader = "N/A"
            else:
                violation_type, change_source, stale_reader = extract_culprits_from_trace(shrunk.trace, shrunk.violation)
            
            verdict = ""
            targets = []
            
            if violation_type == "duplicate":
                verdict = "Declined (duplicate already in history)"
            elif violation_type == "stale_read":
                targets = get_downstream_agents(SSO_SCENARIO, stale_reader)
                
                # Apply cascade repair
                p_after = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
                apply_mutation(p_after, shrunk.mutation)
                for t in targets:
                    p_after.order.append(t)
                
                tr_after = await p_after.run()
                res_after = check_all_invariants(tr_after)
                verdict = "Accepted" if all(r.passed for r in res_after) else "Declined"
            else:
                verdict = "Declined (unknown)"
                
            runs[run_id][s] = {
                "viol_type": violation_type,
                "change_source": change_source,
                "stale_reader": stale_reader,
                "targets": ",".join(targets) if targets else "None",
                "verdict": verdict,
                "shrunk_trace": shrunk.trace,
                "shrunk_violation": shrunk.violation
            }


    print("\n=======================================")
    print("PHASE 2: TRACE-BASED REPAIR TABLE")
    print("=======================================")
    matches_exactly = True
    for s in seeds:
        if runs[1][s]["verdict"] != runs[2][s]["verdict"] or runs[1][s]["targets"] != runs[2][s]["targets"]:
            matches_exactly = False
            
    print(f"Run 1 and Run 2 Match Exactly: {matches_exactly}")
    print(f"{'Seed':<5} | {'Violation':<15} | {'Change Source':<15} | {'Stale Reader':<15} | {'Repair Targets':<30} | {'Verdict':<40}")
    print("-" * 135)
    for s in seeds:
        r = runs[1][s]
        print(f"{s:<5} | {r['viol_type']:<15} | {r['change_source']:<15} | {r['stale_reader']:<15} | {r['targets']:<30} | {r['verdict']:<40}")

    print("\n=======================================")
    print("NARRATION GENERATION (TRACE-ONLY)")
    print("=======================================")
    
    # Pick Seed 6 (stale read) and Seed 18 (duplicate)
    
    s = 6
    print(f"\n--- Seed {s} Narration ---")
    tr = runs[1][s]["shrunk_trace"]
    print("Trace events translated to plain text:")
    trace_text = parse_trace_for_narration(tr)
    print(trace_text)
    print(f"\nRepair Target: {runs[1][s]['targets']}")
    print(f"Verdict: {runs[1][s]['verdict']}")

    s = 18
    print(f"\n--- Seed {s} Narration ---")
    tr = runs[1][s]["shrunk_trace"]
    print("Trace events translated to plain text:")
    trace_text = parse_trace_for_narration(tr)
    print(trace_text)
    print(f"\nRepair Target: {runs[1][s]['targets']}")
    print(f"Verdict: {runs[1][s]['verdict']}")


if __name__ == "__main__":
    asyncio.run(run_phase2())
