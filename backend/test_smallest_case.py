import asyncio
import sys
sys.path.insert(0, '.')

from pipeline import create_pipeline
from scenarios import SSO_SCENARIO
from models import Mutation, MutationType, Commitment, AgentAction
from mutations import apply_mutation
from invariants import check_all_invariants
from llm_client import StubLLMClient

async def test_case():
    llm = StubLLMClient()
    p = create_pipeline(scenario=SSO_SCENARIO, llm=llm)
    
    # 1. Inject fault: implemented_protocol flipped to saml after docs
    m = Mutation(
        type=MutationType.CONTENT_FLIP, 
        target_agent='system', 
        target_key='implemented_protocol', 
        params={'to_value': 'saml', 'flip_after': 'docs'}
    )
    apply_mutation(p, m)
    
    # 2. Run baseline + mutation
    trace = await p.run()
    
    print("=" * 60)
    print("1. BEFORE REPAIR TRACE ACTIONS & COMMITMENTS")
    print("=" * 60)
    for e in trace:
        if isinstance(e, Commitment):
            print(f"  [Commitment] {e.agent_id} -> {e.key}='{e.value}' (v{e.version}, revoked={e.revoked})")
        elif isinstance(e, AgentAction):
            print(f"  [Action] {e.agent_id}: {e.action_type} reads={e.reads} payload={e.payload}")

    res_before = check_all_invariants(trace)
    print("\nInvariants Before Repair:")
    for r in res_before:
        print(f"  - {r.invariant_id}: passed={r.passed} | reason={r.reason}")

    # 3. Cascade Repair
    print("\n" + "=" * 60)
    print("2. RUNNING CASCADE REPAIR ON [qa, deployment, docs]")
    print("=" * 60)
    await p.run_cascade(['qa', 'deployment', 'docs'])

    print("\nTrace Events Added During Repair:")
    for e in p.trace[len(trace):]:
        if isinstance(e, Commitment):
            print(f"  [Commitment] {e.agent_id} -> {e.key}='{e.value}' (v{e.version}, revoked={e.revoked})")
        elif isinstance(e, AgentAction):
            print(f"  [Action] {e.agent_id}: {e.action_type} reads={e.reads} payload={e.payload}")

    res_after = check_all_invariants(p.trace)
    print("\nInvariants After Repair:")
    for r in res_after:
        print(f"  - {r.invariant_id}: passed={r.passed} | reason={r.reason}")

    # 4. Independent Goal Invariant Check
    # Authoritative Goal: If auth != impl, deployment must NOT deploy (must hold).
    # If auth == impl, deployment must deploy.
    latest_auth = p.store.get_latest('auth_protocol')
    latest_impl = p.store.get_latest('implemented_protocol')
    latest_qa = p.store.get_latest('qa_approval')
    
    # Find latest deployment action
    dep_actions = [e for e in p.trace if isinstance(e, AgentAction) and e.agent_id == 'deployment']
    latest_dep_decision = dep_actions[-1].payload.get('decision_result') if dep_actions else None

    print("\n" + "=" * 60)
    print("3. INDEPENDENT GOAL INVARIANT EVALUATION")
    print("=" * 60)
    print(f"  auth_protocol = {latest_auth.value if latest_auth else 'None'}")
    print(f"  implemented_protocol = {latest_impl.value if latest_impl else 'None'}")
    print(f"  qa_approval = {latest_qa.value if latest_qa else 'None'}")
    print(f"  deployment decision = {latest_dep_decision}")

    auth_val = latest_auth.value if latest_auth else ""
    impl_val = latest_impl.value if latest_impl else ""
    
    if auth_val == impl_val:
        goal_passed = (latest_dep_decision == 'deploy')
        expected_status = "deploy"
    else:
        goal_passed = (latest_dep_decision == 'hold')
        expected_status = "hold"
        
    print(f"  Expected deployment outcome: {expected_status}")
    print(f"  Actual deployment outcome:   {latest_dep_decision}")
    print(f"  Authoritative Goal Status:   {'PASSED' if goal_passed else 'FAILED'}")

if __name__ == '__main__':
    asyncio.run(test_case())
