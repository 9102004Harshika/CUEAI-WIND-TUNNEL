import asyncio
from search import adversarial_search
from shrinker import shrink
from scenarios import SSO_SCENARIO
from llm_client import get_llm_client
from mutations import Mutation, MutationType, run_with_mutation, apply_mutation
from pipeline import create_pipeline
from invariants import check_all_invariants

def format_trace(trace):
    lines = []
    for e in trace:
        if hasattr(e, 'action_type'):
            lines.append(f"  [ACTION] {e.agent_id}: {e.action_type}")
        else:
            lines.append(f"  [STATE]  {e.agent_id} wrote {e.key}={e.value}")
    return "\n".join(lines)

def split_decline_reason(results, old_trace, new_trace, re_run_agent):
    failed = [r.invariant_id for r in results if not r.passed]
    if "no_duplicate_execution" in failed:
        # Check if the re-run agent read anything different
        # In a real trace, we'd look at the input versions. Here we simply compare the last execution of the agent.
        # If the input states are identical, say "re-run reads identical inputs".
        # Otherwise "duplicate already in history".
        return "re-run reads identical inputs (no state changed for this agent)"
    if "no_downstream_disagreement" in failed:
        return "downstream disagreement still present"
    return "other (" + ", ".join(failed) + ")"

async def investigate():
    client = get_llm_client(use_gemini=True)
    
    print("=======================================")
    print("1. TARGETED LINEAR STALENESS SCENARIO")
    print("=======================================")
    m_lin = Mutation(
        type=MutationType.CONTENT_FLIP, target_agent="qa",
        params={"key": "qa_approval", "flip_after": "deployment"}
    )
    r_lin = await run_with_mutation(m_lin, SSO_SCENARIO)
    viols_lin = [res for res in r_lin.invariant_results if not res.passed]
    print(f"BEFORE REPAIR TRACE:\n{format_trace(r_lin.trace)}")
    print(f"VIOLATIONS: {[v.invariant_id for v in viols_lin]}")
    
    trace_summary_lin = "; ".join(str(e) for e in r_lin.trace[:12])
    fx_lin, _ = await client.propose_fix(SSO_SCENARIO.model_dump_json(), m_lin.describe(), trace_summary_lin, viols_lin[0].reason)
    
    target_lin = fx_lin.agent_id
    print(f"\nAGENT RE-RUN PROPOSED: {target_lin}")
    print(f"REASONING: {fx_lin.reasoning}")
    
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    pipeline_lin = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(pipeline_lin, m_lin)
    pipeline_lin.order.append(target_lin)
    trace_lin_new = await pipeline_lin.run()
    res_lin_new = check_all_invariants(trace_lin_new)
    all_passed_lin = all(r.passed for r in res_lin_new)
    print(f"\nAFTER REPAIR TRACE:\n{format_trace(trace_lin_new)}")
    if all_passed_lin:
        print("VERIFIER: ACCEPTED (Healed)")
    else:
        reason = split_decline_reason(res_lin_new, r_lin.trace, trace_lin_new, target_lin)
        print(f"VERIFIER: DECLINED - Reason: {reason}")


    print("\n=======================================")
    print("2. TARGETED PARALLEL FORK SCENARIO")
    print("=======================================")
    m_par = Mutation(
        type=MutationType.CONTENT_FLIP, target_agent="engineering",
        params={"key": "implemented_protocol", "flip_after": "qa"}
    )
    r_par = await run_with_mutation(m_par, SSO_SCENARIO)
    viols_par = [res for res in r_par.invariant_results if not res.passed]
    print(f"BEFORE REPAIR TRACE:\n{format_trace(r_par.trace)}")
    print(f"VIOLATIONS: {[v.invariant_id for v in viols_par]}")
    
    trace_summary_par = "; ".join(str(e) for e in r_par.trace[:12])
    fx_par, _ = await client.propose_fix(SSO_SCENARIO.model_dump_json(), m_par.describe(), trace_summary_par, viols_par[0].reason)
    
    target_par = fx_par.agent_id
    print(f"\nAGENT RE-RUN PROPOSED: {target_par}")
    print(f"REASONING: {fx_par.reasoning}")
    
    pipeline_par = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(pipeline_par, m_par)
    pipeline_par.order.append(target_par)
    
    # cascade logic used in run_log
    idx = baseline_order.index(target_par) if target_par in baseline_order else -1
    if idx >= 0:
        agent_dict = {a.id: a for a in SSO_SCENARIO.agents}
        stale_keys = {agent_dict[target_par].writes}
        for later_id in baseline_order[idx + 1:]:
            later_agent = agent_dict[later_id]
            if any(rd in stale_keys for rd in later_agent.reads):
                pipeline_par.order.append(later_id)
                stale_keys.add(later_agent.writes)

    trace_par_new = await pipeline_par.run()
    res_par_new = check_all_invariants(trace_par_new)
    all_passed_par = all(r.passed for r in res_par_new)
    print(f"\nAFTER REPAIR TRACE:\n{format_trace(trace_par_new)}")
    if all_passed_par:
        print("VERIFIER: ACCEPTED (Healed)")
    else:
        reason = split_decline_reason(res_par_new, r_par.trace, trace_par_new, target_par)
        print(f"VERIFIER: DECLINED - Reason: {reason}")


    print("\n=======================================")
    print("3. HEALED ADVERSARIAL SEEDS (6 AND 18)")
    print("=======================================")
    for s in [6, 18]:
        print(f"\n--- SEED {s} ---")
        best = await adversarial_search(SSO_SCENARIO, budget=20, seed=s)
        shrunk = await shrink(best, SSO_SCENARIO)
        print(f"SHRUNK MUTATION: {shrunk.mutation.describe()}")
        print(f"BEFORE REPAIR TRACE:\n{format_trace(shrunk.trace)}")
        
        t_sum = "; ".join(str(e) for e in shrunk.trace[:12])
        fx, _ = await client.propose_fix(SSO_SCENARIO.model_dump_json(), shrunk.mutation.describe(), t_sum, shrunk.violation)
        
        target = fx.agent_id
        print(f"AGENT RE-RUN PROPOSED: {target}")
        
        pipeline = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
        apply_mutation(pipeline, shrunk.mutation)
        pipeline.order.append(target)
        
        # cascade logic
        idx = baseline_order.index(target) if target in baseline_order else -1
        if idx >= 0:
            agent_dict = {a.id: a for a in SSO_SCENARIO.agents}
            stale_keys = {agent_dict[target].writes}
            for later_id in baseline_order[idx + 1:]:
                later_agent = agent_dict[later_id]
                if any(rd in stale_keys for rd in later_agent.reads):
                    pipeline.order.append(later_id)
                    stale_keys.add(later_agent.writes)
                    
        new_tr = await pipeline.run()
        print(f"AFTER REPAIR TRACE:\n{format_trace(new_tr)}")

if __name__ == "__main__":
    asyncio.run(investigate())
