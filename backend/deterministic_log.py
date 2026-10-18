import asyncio
import io
import sys

# Wrap stdout to utf-8 safely
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from scenarios import SSO_SCENARIO
from search import adversarial_search
from shrinker import shrink
from llm_client import get_llm_client
from pipeline import create_pipeline
from mutations import apply_mutation, Mutation, MutationType
from invariants import check_all_invariants

def format_invariants(results):
    v = []
    for r in results:
        v.append(f"{r.invariant_id}({'P' if r.passed else 'F'})")
    return " ".join(v)

def format_trace_for_narration(trace):
    lines = []
    for e in trace:
        if hasattr(e, 'action_type'):
            if e.action_type == "content_flip":
                lines.append(f"[Mutation Applied] System changed a value.")
            else:
                lines.append(f"{e.agent_id} read {len(e.reads)} inputs and executed.")
        else:
            lines.append(f"State updated: {e.key}={e.value}")
    return " | ".join(lines)

def mutation_to_trace_summary(mutation, trace):
    if mutation.type.name != "CONTENT_FLIP":
        return mutation.describe()
    
    # Try to find exactly what was flipped from the trace
    flip_event = None
    for e in trace:
        if hasattr(e, 'action_type') and e.action_type == "content_flip":
            flip_event = e
            break
            
    if not flip_event:
        return mutation.describe()
        
    c = None
    for e in trace:
        if not hasattr(e, 'action_type') and e.id in flip_event.reads:
            c = e
            break
            
    if c:
        return f"System flipped '{c.key}' to '{c.value}' after {mutation.params.get('flip_after', 'someone')} executed."
    return mutation.describe()

async def run_targeted():
    print("=======================================")
    print("TARGETED SCENARIOS (CASCADE FIXED)")
    print("=======================================")
    client = get_llm_client(use_gemini=True)
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    
    scenarios = [
        ("flip after deployment", "deploy_action", "deploy", "rollback", "deployment"),
        ("flip before deployment (after qa)", "qa_approval", "approved", "rejected", "qa"),
    ]
    
    for name, target_key, from_v, to_v, flip_after in scenarios:
        print(f"\n--- SCENARIO: {name} ---")
        m = Mutation(
            type=MutationType.CONTENT_FLIP, target_agent="system",
            params={"target_key": target_key, "from_value": from_v, "to_value": to_v, "flip_after": flip_after}
        )
        
        p = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
        apply_mutation(p, m)
        tr = await p.run()
        res_before = check_all_invariants(tr)
        viols = [r for r in res_before if not r.passed]
        
        print(f"BEFORE Invariants: {format_invariants(res_before)}")
        if not viols:
            print("No violations found. Skipping repair.")
            continue
            
        fx, _ = await client.propose_fix(
            SSO_SCENARIO.model_dump_json(), mutation_to_trace_summary(m, tr), 
            "; ".join(str(e) for e in tr[:12]), viols[0].reason
        )
        target = fx.agent_id
        print(f"Repair target proposed by LLM: {target}")
        
        p_after = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
        apply_mutation(p_after, m)
        p_after.order.append(target)
        
        idx = baseline_order.index(target) if target in baseline_order else -1
        cascaded = []
        if idx >= 0:
            agent_dict = {a.id: a for a in SSO_SCENARIO.agents}
            stale_keys = {agent_dict[target].writes}
            for later_id in baseline_order[idx + 1:]:
                later_agent = agent_dict[later_id]
                if any(rd in stale_keys for rd in later_agent.reads):
                    p_after.order.append(later_id)
                    stale_keys.add(later_agent.writes)
                    cascaded.append(later_id)
                    
        print(f"Cascade appended: {cascaded}")
        tr_after = await p_after.run()
        res_after = check_all_invariants(tr_after)
        
        print(f"AFTER Invariants: {format_invariants(res_after)}")
        if all(r.passed for r in res_after):
            print("VERDICTOR: ACCEPTED (HEALED)")
        else:
            print("VERDICTOR: DECLINED")


async def build_seed_table():
    client = get_llm_client(use_gemini=False) # Use stub for reproducible table generation
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    
    seeds = list(range(1, 21))
    runs = {1: {}, 2: {}}
    
    for run_id in [1, 2]:
        print(f"\nGeneraring Log Run {run_id}...")
        for s in seeds:
            best = await adversarial_search(SSO_SCENARIO, budget=20, seed=s)
            shrunk = await shrink(best, SSO_SCENARIO)
            
            p = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
            apply_mutation(p, shrunk.mutation)
            tr = await p.run()
            res_before = check_all_invariants(tr)
            
            viols_b = [r for r in res_before if not r.passed]
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
            
    print("\n=======================================")
    print("DETERMINISM TABLE")
    print("=======================================")
    matches_exactly = True
    for s in seeds:
        r1 = runs[1][s]
        r2 = runs[2][s]
        if r1 != r2:
            matches_exactly = False
            
    print(f"Run 1 and Run 2 Match Exactly: {matches_exactly}")
    print(f"{'Seed':<5} | {'First Mut':<15} | {'Shrunk Mut':<15} | {'Outcome':<10} | {'Before':<60} | {'After':<60}")
    print("-" * 180)
    for s in seeds:
        r = runs[1][s]
        print(f"{s:<5} | {r['first_mut']:<15} | {r['shrunk_mut']:<15} | {r['outcome']:<10} | {r['before']:<60} | {r['after']:<60}")


async def seed_18_specifically():
    client = get_llm_client(use_gemini=False)
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    
    print("\n=======================================")
    print("SEED 18 SPECIFICALLY")
    print("=======================================")
    best = await adversarial_search(SSO_SCENARIO, budget=20, seed=18)
    shrunk = await shrink(best, SSO_SCENARIO)
    
    p = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(p, shrunk.mutation)
    tr = await p.run()
    res_before = check_all_invariants(tr)
    
    fx_target = "qa"
    p_after = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(p_after, shrunk.mutation)
    p_after.order.append(fx_target)
    
    idx = baseline_order.index(fx_target) if fx_target in baseline_order else -1
    if idx >= 0:
        agent_dict = {a.id: a for a in SSO_SCENARIO.agents}
        stale_keys = {agent_dict[fx_target].writes}
        for later_id in baseline_order[idx + 1:]:
            later_agent = agent_dict[later_id]
            if any(rd in stale_keys for rd in later_agent.reads):
                p_after.order.append(later_id)
                stale_keys.add(later_agent.writes)
                
    tr_after = await p_after.run()
    res_after = check_all_invariants(tr_after)

    def print_trace(tr):
        for e in tr:
            if hasattr(e, 'action_type'):
                print(f"  [ACTION] {e.agent_id}: {e.action_type}")
            else:
                print(f"  [STATE]  {e.agent_id} wrote {e.key}={e.value} (v{e.version})")

    print("BEFORE TRACE:")
    print_trace(tr)
    print(f"BEFORE INVARIANTS: {format_invariants(res_before)}")
    
    print("\nAFTER TRACE (Target QA):")
    print_trace(tr_after)
    print(f"AFTER INVARIANTS: {format_invariants(res_after)}")
    
    verdict = "ACCEPTED" if all(r.passed for r in res_after) else "DECLINED"
    print(f"VERDICT: {verdict}")
    

async def main():
    await run_targeted()
    await build_seed_table()
    await seed_18_specifically()

if __name__ == "__main__":
    asyncio.run(main())
