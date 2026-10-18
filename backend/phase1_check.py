import asyncio
import io
import sys
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from scenarios import SSO_SCENARIO
from search import adversarial_search
from shrinker import shrink
from llm_client import get_llm_client
from mutations import apply_mutation
from pipeline import create_pipeline
from invariants import check_all_invariants

def derive_culprit(violation_string):
    match = re.search(r"^(\w+)(?:'s active| executed)", violation_string)
    if match:
        return match.group(1)
    if "Deployment" in violation_string:
        return "deployment"
    return "unknown"

async def check_phase1():
    client = get_llm_client(use_gemini=True)
    seeds = list(range(1, 21))
    
    print(f"{'Seed':<5} | {'Proposed Target':<15} | {'Source / Model':<30} | {'Derived Culprit':<15} | {'Matches':<10} | {'Complexity Before->After'}")
    print("-" * 115)
    
    for s in seeds:
        best = await adversarial_search(SSO_SCENARIO, budget=20, seed=s)
        shrunk = await shrink(best, SSO_SCENARIO)
        
        # Derive culprit from violation text
        culprit = derive_culprit(shrunk.violation)
        
        # Generate repair target using GEMINI
        trace_sum = "; ".join(str(e) for e in shrunk.trace[:12])
        fx, source_label = await client.propose_fix(
            SSO_SCENARIO.model_dump_json(), shrunk.mutation.describe(), trace_sum, shrunk.violation
        )
        
        target = fx.agent_id
        model_id = "gemini-3.1-flash-lite" if "gemini" in source_label else "none"
        source = f"{source_label} / {model_id}"
        matches = str(target.lower() == culprit.lower())
        c_before = best.mutation.complexity()
        c_after = shrunk.mutation.complexity()
        
        print(f"{s:<5} | {target:<15} | {source:<30} | {culprit:<15} | {matches:<10} | {str(c_before) + ' -> ' + str(c_after)}")

if __name__ == "__main__":
    asyncio.run(check_phase1())
