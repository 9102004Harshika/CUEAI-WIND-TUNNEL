import asyncio
import io
import sys
import re
from typing import Dict, Any

from scenarios import SSO_SCENARIO
from mutations import apply_mutation, Mutation, MutationType, random_mutation
from pipeline import create_pipeline
from invariants import check_all_invariants
from check_culprits import extract_stale_reader_and_change_source
from llm_client import get_llm_client
from phase2 import get_downstream_agents




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

async def run_sweep():
    client = get_llm_client(use_gemini=False)
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    
    mutation_types = [
        MutationType.DELAY,
        MutationType.REORDER,
        MutationType.CONTENT_FLIP,
        MutationType.DUPLICATE,
        MutationType.REVOKE
    ]
    
    results: Dict[str, Dict[str, int]] = {}
    
    print("=======================================")
    print("PHASE 3: STALE-READ SWEEP (10x per MUTATION TYPE)")
    print("=======================================")
    
    for mtype in mutation_types:
        name = mtype.name
        results[name] = {
            "total_violations": 0,
            "repairs_accepted": 0,
            "repairs_declined_duplicate": 0,
            "repairs_declined_failed_cascades": 0
        }
        
        # We will loop until we gather 10 violations for this mutation type
        # Or we cap at 50 attempts
        violations_found = 0
        attempts = 0
        import random
        random.seed(42 + list(MutationType).index(mtype))
        
        while violations_found < 10 and attempts < 100:
            attempts += 1
            
            # Manually generate valid variations
            agent_ids = baseline_order
            m = None
            if mtype == MutationType.DELAY:
                m = Mutation(type=mtype, target_agent=random.choice(agent_ids[1:]), params={"delay_seconds": random.randint(2, 20)})
            elif mtype == MutationType.REORDER:
                m = Mutation(type=mtype, target_agent=random.choice(agent_ids[:-1]), params={"swap_with": random.choice(agent_ids)})
            elif mtype == MutationType.CONTENT_FLIP:
                realistic_values = ["saml", "oidc", "token_refresh", "legacy_auth", "expired_cert", "revoked", "v2_api", "disabled"]
                m = Mutation(type=mtype, target_agent="system", target_key=random.choice(["auth_protocol", "implemented_protocol", "qa_approval", "deploy_action"]), params={"from_value": "oauth", "to_value": random.choice(realistic_values), "flip_after": random.choice(agent_ids)})
            elif mtype == MutationType.DUPLICATE:
                m = Mutation(type=mtype, target_agent=random.choice(agent_ids))
            elif mtype == MutationType.REVOKE:
                m = Mutation(type=mtype, target_agent="system", target_key=random.choice(["auth_protocol", "implemented_protocol", "qa_approval"]), params={"revoke_after": random.choice(agent_ids)})
                
            p = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
            # Ensure it generates cleanly
            try:
                apply_mutation(p, m)
                tr = await p.run()
                res_before = check_all_invariants(tr)
            except Exception:
                continue
                
            has_viol = sum(1 for r in res_before if not r.passed) > 0
            if has_viol:
                violations_found += 1
                results[name]["total_violations"] += 1
                
                # Prioritize duplicates
                has_dup = False
                for r in res_before:
                    if r.invariant_id == "no_duplicate_execution" and not r.passed:
                        has_dup = True
                        break
                        
                if has_dup:
                    results[name]["repairs_declined_duplicate"] += 1
                else:
                    violation_reason = next(r.reason for r in res_before if not r.passed)
                    viol_type, change_source, stale_reader = extract_culprits_from_trace(tr, violation_reason)
                    
                    if viol_type == "stale_read":
                        targets = get_downstream_agents(SSO_SCENARIO, stale_reader)
                        if not targets:
                            results[name]["repairs_declined_failed_cascades"] += 1
                            continue
                            
                        # Apply cascade repair
                        p_after = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
                        apply_mutation(p_after, m)
                        for t in targets:
                            p_after.order.append(t)
                        
                        tr_after = await p_after.run()
                        res_after = check_all_invariants(tr_after)
                        if all(r.passed for r in res_after):
                            results[name]["repairs_accepted"] += 1
                        else:
                            results[name]["repairs_declined_failed_cascades"] += 1
                    else:
                        results[name]["repairs_declined_failed_cascades"] += 1
                        
    print(f"{'Mutation Type':<20} | {'Violations Logged':<20} | {'Accepted':<10} | {'Declined (Dup)':<15} | {'Declined (Fail)':<15}")
    print("-" * 90)
    for name, data in results.items():
        print(f"{name:<20} | {data['total_violations']:<20} | {data['repairs_accepted']:<10} | {data['repairs_declined_duplicate']:<15} | {data['repairs_declined_failed_cascades']:<15}")

if __name__ == "__main__":
    asyncio.run(run_sweep())
