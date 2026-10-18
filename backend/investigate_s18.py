import asyncio
import sys
import io

# wrapper to force utf8 on stdout so windows doesn't crash on print()
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from pipeline import create_pipeline
from scenarios import SSO_SCENARIO
from mutations import Mutation, MutationType, apply_mutation
from llm_client import get_llm_client
from invariants import check_all_invariants

def format_trace(trace):
    lines = []
    for e in trace:
        if hasattr(e, 'action_type'):
            lines.append(f"  [ACTION] {e.agent_id}: {e.action_type} (reads: {e.reads_versions})")
        else:
            lines.append(f"  [STATE]  {e.agent_id} wrote {e.key}={e.value} (v{e.version})")
    return "\n".join(lines)

async def investigate_specifics():
    client = get_llm_client(use_gemini=False)
    
    print("=== SEED 18 INVESTIGATION ===")
    m = Mutation(
        type=MutationType.DUPLICATE,
        target_agent="engineering"
    )
    
    # 1. Before Repair
    baseline_order = [a.id for a in SSO_SCENARIO.agents]
    p_before = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(p_before, m)
    trace_before = await p_before.run()
    res_before = check_all_invariants(trace_before)
    
    print("BEFORE TRACE:")
    print(format_trace(trace_before))
    print("BEFORE INVARIANTS:")
    for r in res_before:
        print(f"  {r.invariant_id}: {'PASS' if r.passed else 'FAIL - ' + str(r.reason)}")

    # 2. After Repair (target QA)
    p_after = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(p_after, m)
    p_after.order.append("qa")
    
    # cascade
    idx = baseline_order.index("qa")
    stale_keys = {"qa_approval"}
    for later_id in baseline_order[idx + 1:]:
        later_agent = {a.id: a for a in SSO_SCENARIO.agents}[later_id]
        if any(rd in stale_keys for rd in later_agent.reads):
            p_after.order.append(later_id)
            stale_keys.add(later_agent.writes)
            
    trace_after = await p_after.run()
    res_after = check_all_invariants(trace_after)
    print("\nAFTER TRACE:")
    print(format_trace(trace_after))
    print("AFTER INVARIANTS:")
    for r in res_after:
        print(f"  {r.invariant_id}: {'PASS' if r.passed else 'FAIL - ' + str(r.reason)}")
        
    print("\n=== CASCADE LOGIC EXPLANATION ===")
    print("Cascade Target: qa (Index 2)")
    print("Stale Keys Initial: {'qa_approval'}")
    print("Checking 'deployment' (reads ['qa_approval', 'implemented_protocol']):")
    print("  Intersects stale_keys? Yes! Append deployment.")
    print("  stale_keys now: {'qa_approval', 'deploy_action'}")
    print("Checking 'docs' (reads ['auth_protocol', 'implemented_protocol']):")
    print("  Intersects stale_keys? No! Skip docs.")
    
    print("\n=== REAL TARGETED LINEAR ===")
    m_lin = Mutation(
        type=MutationType.CONTENT_FLIP, target_agent="system",
        params={"target_key": "qa_approval", "from_value": "approved", "to_value": "rejected", "flip_after": "deployment"}
    )
    p_lin = create_pipeline(scenario=SSO_SCENARIO, order=baseline_order.copy(), llm=client)
    apply_mutation(p_lin, m_lin)
    tr_lin = await p_lin.run()
    print("LINEAR TRACE (FLIP QA AFTER DEPLOYMENT):")
    print(format_trace(tr_lin))
    res_lin = check_all_invariants(tr_lin)
    for r in res_lin:
        print(f"  {r.invariant_id}: {'PASS' if r.passed else 'FAIL - ' + str(r.reason)}")


if __name__ == "__main__":
    asyncio.run(investigate_specifics())
