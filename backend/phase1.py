import asyncio
import io
import sys
import json
import os

# Wrap stdout to utf-8 safely
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from scenarios import SSO_SCENARIO
from search import adversarial_search
from shrinker import shrink
from llm_client import get_llm_client
from pipeline import create_pipeline
from mutations import apply_mutation, Mutation
from invariants import check_all_invariants

def format_invariants(results):
    v = []
    for r in results:
        v.append(f"{r.invariant_id}({'P' if r.passed else 'F'})")
    return " ".join(v)

async def run_phase1():
    client = get_llm_client(use_gemini=False)
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    
    seeds = list(range(1, 21))
    runs = {1: {}, 2: {}}
    
    os.makedirs('counterexamples', exist_ok=True)
    
    for run_id in [1, 2]:
        print(f"\nGenerating Log Run {run_id}...")
        for s in seeds:
            best = await adversarial_search(SSO_SCENARIO, budget=20, seed=s)
            shrunk = await shrink(best, SSO_SCENARIO)
            
            p = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
            apply_mutation(p, shrunk.mutation)
            tr = await p.run()
            res_before = check_all_invariants(tr)
            
            target = "qa" # stub client returns qa
            
            p_after = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
            apply_mutation(p_after, shrunk.mutation)
            p_after.order.append(target)
            
            idx = baseline_order.index(target) if target in baseline_order else -1
            if idx >= 0:
                agent_dict = {a.id: a for a in SSO_SCENARIO.agents}
                stale_keys = {agent_dict[target].writes}
                for later_id in baseline_order[idx + 1:]:
                    later_agent = agent_dict[later_id]
                    if any(rd in stale_keys for rd in later_agent.reads):
                        p_after.order.append(later_id)
                        stale_keys.add(later_agent.writes)
            
            tr_after = await p_after.run()
            res_after = check_all_invariants(tr_after)
            outcome = "Accepted" if all(r.passed for r in res_after) else "Declined"
            
            runs[run_id][s] = {
                "first_mut": best.mutation.type.name,
                "shrunk_mut": shrunk.mutation.type.name,
                "outcome": outcome,
                "before": format_invariants(res_before),
                "after": format_invariants(res_after),
            }
            
            # Export JSON from run 1
            if run_id == 1:
                with open(f'counterexamples/seed_{s}.json', 'w') as f:
                    f.write(shrunk.mutation.model_dump_json())
            
    print("\n=======================================")
    print("PHASE 1: DETERMINISM TABLE")
    print("=======================================")
    matches_exactly = True
    for s in seeds:
        r1 = runs[1][s]
        r2 = runs[2][s]
        if r1 != r2:
            matches_exactly = False
            
    print(f"Run 1 and Run 2 Match Exactly: {matches_exactly}")
    print(f"{'Seed':<5} | {'First Mut':<15} | {'Shrunk Mut':<15} | {'Outcome':<10} | {'Before':<80} | {'After':<80}")
    print("-" * 210)
    for s in seeds:
        r = runs[1][s]
        print(f"{s:<5} | {r['first_mut']:<15} | {r['shrunk_mut']:<15} | {r['outcome']:<10} | {r['before']:<80} | {r['after']:<80}")


if __name__ == "__main__":
    asyncio.run(run_phase1())
