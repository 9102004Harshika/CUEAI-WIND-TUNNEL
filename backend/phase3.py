import asyncio
import io
import sys
import re



from scenarios import SSO_SCENARIO
from search import adversarial_search
from shrinker import shrink
from llm_client import get_llm_client
from mutations import apply_mutation
from pipeline import create_pipeline
from invariants import check_all_invariants

def parse_trace_for_narration(trace, violation_text, verdict):
    lines = []
    commitmap = {}
    for e in trace:
        if not hasattr(e, 'action_type'):
            commitmap[e.id] = (e.key, e.version)
            
    for e in trace:
        if hasattr(e, 'action_type'):
            if e.action_type == "content_flip":
                key_name = commitmap.get(e.produced_commitment_id, ('unknown', 0))[0]
                lines.append(f"[Mutation] System flipped {key_name}.")
            elif e.action_type == "delay":
                lines.append(f"[Mutation] System delayed {e.agent_id}.")
            else:
                reads = []
                for cid in e.reads:
                    k, v = commitmap.get(cid, ('unknown', 0))
                    reads.append(f"{k} v{v}")
                if reads:
                    lines.append(f"[{e.agent_id}] read {', '.join(reads)}")
        else:
            lines.append(f"[{e.agent_id}] wrote {e.key}={e.value} (v{e.version})")
            
    lines.append(f"\n[Broken Invariant] {violation_text}")
    lines.append(f"[Verdict] Repair {verdict.lower()}")
    return "\n".join(lines)


def extract_culprits_from_trace(trace, violation_text):
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


async def run_phase3_table():
    client = get_llm_client(use_gemini=False)
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    
    seeds = list(range(1, 21))
    runs = {1: {}, 2: {}}
    
    for run_id in [1, 2]:
        print(f"\nGenerating Phase 3 Log Run {run_id}...")
        for s in seeds:
            best = await adversarial_search(SSO_SCENARIO, budget=20, seed=s)
            shrunk = await shrink(best, SSO_SCENARIO)
            
            p = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
            apply_mutation(p, shrunk.mutation)
            tr = await p.run()
            res_before = check_all_invariants(tr)
            
            has_dup = False
            dup_agent = "unknown"
            for r in res_before:
                if r.invariant_id == "no_duplicate_execution" and not r.passed:
                    has_dup = True
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
                
                p_after = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
                apply_mutation(p_after, shrunk.mutation)
                for t in targets:
                    p_after.order.append(t)
                
                tr_after = await p_after.run()
                res_after = check_all_invariants(tr_after)
                verdict = "Accepted" if all(r.passed for r in res_after) else "Declined (failed invariants after cascade)"
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
    print("PHASE 3: HONEST QA STUB + REALISTIC VALUES TABLE")
    print("=======================================")
    matches_exactly = True
    for s in seeds:
        if runs[1][s]["verdict"] != runs[2][s]["verdict"]:
            matches_exactly = False
            
    print(f"Run 1 and Run 2 Match Exactly: {matches_exactly}")
    print(f"{'Seed':<4} | {'Violation':<15} | {'Change Source':<13} | {'Stale Reader':<12} | {'Repair Targets':<15} | {'Verdict':<40}")
    print("-" * 110)
    for s in seeds:
        r = runs[1][s]
        print(f"{s:<4} | {r['viol_type']:<15} | {r['change_source']:<13} | {r['stale_reader']:<12} | {r['targets']:<15} | {r['verdict']:<40}")

    return runs[1]

async def run_phase3_narration(run_results):
    client = get_llm_client(use_gemini=True) # use LLM to summarize
    print("\n=======================================")
    print("NARRATION GENERATION")
    print("=======================================")
    
    for s in [6, 18]:
        r = run_results[s]
        trace_text = parse_trace_for_narration(r["shrunk_trace"], r["shrunk_violation"], r["verdict"])
        
        print(f"\n--- Seed {s} Narration (Ground Truth from Trace) ---")
        print(trace_text)
        
        print(f"\n--- Seed {s} Summary (from gemini-3.1-flash-lite) ---")
        # prompt gemini for 3 sentence summary
        prompt = f"Summarize this trace in 3 sentences max. Focus on the progression, the mutation, the violation and the repair verdict:\n\n{trace_text}"
        
        if hasattr(client, '_call_gemini'):
            summary, _ = await client._call_gemini([{"role": "user", "content": prompt}], max_tokens=150)
        else:
            summary, _ = await client.explain_failure("mock", "mock", "mock", trace_text)
            
        print(summary)


async def main():
    results = await run_phase3_table()
    await run_phase3_narration(results)

if __name__ == "__main__":
    asyncio.run(main())
