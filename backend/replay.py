import asyncio
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from scenarios import SSO_SCENARIO
from llm_client import get_llm_client
from pipeline import create_pipeline
from mutations import apply_mutation, Mutation
from invariants import check_all_invariants

def format_invariants(results):
    v = []
    for r in results:
        v.append(f"{r.invariant_id}({'P' if r.passed else 'F'})")
    return " ".join(v)

async def replay_mutation(filepath):
    print(f"\n=======================================")
    print(f"REPLAYING: {filepath}")
    print(f"=======================================")
    
    with open(filepath, 'r') as f:
        m_json = f.read()
    
    m = Mutation.model_validate_json(m_json)
    client = get_llm_client(use_gemini=False)
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    
    p = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(p, m)
    tr = await p.run()
    res_before = check_all_invariants(tr)
    
    print("BEFORE INVARIANTS:")
    print(format_invariants(res_before))
    
    target = "qa" 
    p_after = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(p_after, m)
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
    
    print("\nAFTER INVARIANTS (Target QA):")
    print(format_invariants(res_after))
    
    verdict = "ACCEPTED" if all(r.passed for r in res_after) else "DECLINED"
    print(f"VERDICT: {verdict}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(replay_mutation(sys.argv[1]))
    else:
        print("Usage: python replay.py counterexamples/seed_X.json")
