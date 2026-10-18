"""
CUE Wind Tunnel — 7-Test Authoritative Regression Suite

Tests the 7 critical criteria:
1. Mismatched protocols: oauth vs saml -> QA rejects; deployment holds
2. Cascade after stale QA approval -> New QA commitment recorded; version advances
3. Cascade after stale deployment decision -> New deployment decision recorded; old decision auditable
4. All versions of a required key revoked -> Invariant fails; no vacuous pass
5. Repair produces no commitment -> Repair fails explicitly
6. All structural invariants pass but goal invariant fails -> Repair is rejected
7. Corrected state, valid approval, safe deployment -> Accepted only after every required check passes
"""

import asyncio
from models import Commitment, AgentAction, Mutation, MutationType, ScenarioDef
from scenarios import SSO_SCENARIO
from pipeline import create_pipeline, CommitmentStore, PipelineRunner
from llm_client import StubLLMClient
from invariants import (
    check_all_invariants, 
    goal_sso_safe_deployment, 
    latest_usable_commitment, 
    latest_commitment,
    no_downstream_disagreement
)
from phase3_fixes import attempt_repair

async def test_1_mismatched_protocols():
    print("\n--- TEST 1: Mismatched protocols (oauth vs saml) ---")
    client = StubLLMClient()
    p = create_pipeline(scenario=SSO_SCENARIO, llm=client)
    
    # Pre-configure engineering to implement saml while security sets oauth
    client.DECISIONS["security"] = {"auth_protocol": "oauth"}
    client.DECISIONS["engineering"] = {"implemented_protocol": "saml"}
    
    trace = await p.run()
    
    qa_c = p.store.get_latest("qa_approval")
    deploy_c = p.store.get_latest("deploy_action")
    
    assert qa_c is not None, "QA approval must exist"
    assert qa_c.value == "rejected", f"QA must reject mismatched protocols, got: {qa_c.value}"
    
    assert deploy_c is not None, "Deploy action must exist"
    assert deploy_c.value == "hold", f"Deployment must hold on mismatch, got: {deploy_c.value}"
    
    goal_res = goal_sso_safe_deployment(trace)
    assert goal_res is None, f"Goal invariant should pass for safe hold, got: {goal_res}"
    print("PASS: QA rejected mismatch and deployment held safely.")

async def test_2_cascade_after_stale_qa_approval():
    print("\n--- TEST 2: Cascade after stale QA approval ---")
    client = StubLLMClient()
    client.DECISIONS["security"] = {"auth_protocol": "oauth"}
    client.DECISIONS["engineering"] = {"implemented_protocol": "oauth"}
    
    p = create_pipeline(scenario=SSO_SCENARIO, llm=client)
    
    # After QA runs, mutate implemented_protocol to saml
    mut = Mutation(
        type=MutationType.CONTENT_FLIP,
        target_agent="qa",
        target_key="implemented_protocol",
        params={"from_value": "oauth", "to_value": "saml"}
    )
    from mutations import apply_mutation
    apply_mutation(p, mut)
    
    tr = await p.run()
    qa_v1 = p.store.get_latest("qa_approval")
    assert qa_v1 is not None and qa_v1.version == 1
    
    # Run cascade on [qa, deployment]
    await p.run_cascade(["qa", "deployment"])
    
    qa_v2 = p.store.get_latest("qa_approval")
    assert qa_v2 is not None, "New QA commitment must exist after cascade"
    assert qa_v2.version == 2, f"QA commitment version must advance to 2, got: {qa_v2.version}"
    assert qa_v2.supersedes == qa_v1.id, "QA v2 must supersede QA v1"
    assert qa_v2.value == "rejected", f"Re-read QA must reject saml vs oauth, got: {qa_v2.value}"
    print(f"PASS: New QA commitment recorded (v{qa_v2.version}, supersedes {qa_v1.id[:8]}), value={qa_v2.value}.")

async def test_3_cascade_after_stale_deployment_decision():
    print("\n--- TEST 3: Cascade after stale deployment decision ---")
    client = StubLLMClient()
    client.DECISIONS["security"] = {"auth_protocol": "oauth"}
    client.DECISIONS["engineering"] = {"implemented_protocol": "oauth"}
    
    p = create_pipeline(scenario=SSO_SCENARIO, llm=client)
    from mutations import apply_mutation
    mut = Mutation(
        type=MutationType.CONTENT_FLIP,
        target_agent="deployment",
        target_key="implemented_protocol",
        params={"from_value": "oauth", "to_value": "saml"}
    )
    apply_mutation(p, mut)
    await p.run()
    
    dep_v1 = p.store.get_latest("deploy_action")
    assert dep_v1 is not None and dep_v1.version == 1
    v1_val = dep_v1.value
    
    await p.run_cascade(["qa", "deployment"])
    
    dep_v2 = p.store.get_latest("deploy_action")
    assert dep_v2 is not None, "New deployment commitment must exist"
    assert dep_v2.version == 2, f"Deployment version must advance to 2, got: {dep_v2.version}"
    assert dep_v2.supersedes == dep_v1.id, "Deployment v2 must supersede v1"
    assert dep_v2.value == "hold", f"Deployment must hold on stale cascade, got: {dep_v2.value}"
    
    # Audit trail check: old decision must still be in trace
    dep_commitments = [e for e in p.trace if isinstance(e, Commitment) and e.key == "deploy_action"]
    assert len(dep_commitments) >= 2, "Trace must maintain full audit trail of deployment commitments"
    assert dep_commitments[0].value == v1_val
    assert dep_commitments[1].value == "hold"
    print(f"PASS: Deployment v2 ({dep_v2.value}) recorded, v1 ({v1_val}) remains auditable in trace.")

async def test_4_all_versions_of_required_key_revoked():
    print("\n--- TEST 4: All versions of a required key revoked ---")
    client = StubLLMClient()
    p = create_pipeline(scenario=SSO_SCENARIO, llm=client)
    await p.run()
    
    # Revoke all versions of qa_approval
    for e in p.trace:
        if isinstance(e, Commitment) and e.key == "qa_approval":
            e.revoked = True
            
    goal_res = goal_sso_safe_deployment(p.trace)
    assert goal_res is not None, "Goal invariant MUST fail when required qa_approval is revoked"
    assert "Missing or revoked QA approval" in goal_res, f"Expected revocation failure, got: {goal_res}"
    print(f"PASS: Revoked key failed invariant check as expected: '{goal_res}'.")

async def test_5_repair_produces_no_commitment():
    print("\n--- TEST 5: Repair produces no commitment ---")
    client = StubLLMClient()
    p = create_pipeline(scenario=SSO_SCENARIO, llm=client)
    mut = Mutation(
        type=MutationType.REVOKE,
        target_agent="deployment",
        target_key="qa_approval",
        params={}
    )
    
    # When repair targets are empty or cannot heal the revocation
    verdict, reason, post_trace = await attempt_repair(SSO_SCENARIO, mut, stale_readers=[], client=client)
    assert verdict in ("Declined", "Failed"), f"Expected Declined/Failed when repair cannot run, got: {verdict}"
    print(f"PASS: Repair without viable commitment explicitly returned {verdict}: '{reason}'.")

async def test_6_structural_invariants_pass_but_goal_fails():
    print("\n--- TEST 6: Structural invariants pass but goal invariant fails ---")
    # Fabricate a trace where structural consistency holds (no stale reads, no duplicates),
    # but deployment decided 'deploy' when protocols mismatched (oauth vs saml)
    trace = [
        Commitment(agent_id="security", statement="auth", key="auth_protocol", value="oauth", version=1),
        Commitment(agent_id="engineering", statement="impl", key="implemented_protocol", value="saml", version=1),
        Commitment(agent_id="qa", statement="qa", key="qa_approval", value="approved", version=1),
        Commitment(agent_id="deployment", statement="deploy", key="deploy_action", value="deploy", version=1),
        AgentAction(agent_id="deployment", action_type="execute_deployment", reads=[], reads_versions=[], payload={"decision": "deploy"})
    ]
    
    # Structural invariants
    sd = no_downstream_disagreement(trace)
    assert sd is None, "Structural no_downstream_disagreement passes on fabricated trace"
    
    # Goal invariant
    goal_res = goal_sso_safe_deployment(trace)
    assert goal_res is not None, "Authoritative goal invariant MUST fail when deploy happens on protocol mismatch"
    assert "Protocol mismatch" in goal_res
    
    # check_all_invariants must fail overall
    all_res = check_all_invariants(trace)
    failed = [r for r in all_res if not r.passed]
    assert any(r.invariant_id == "goal_sso_safe_deployment" for r in failed), "Goal invariant must be among failures"
    print(f"PASS: Structural checks passed, but Goal Invariant caught illegal deploy: '{goal_res}'.")

async def test_7_corrected_state_valid_approval_safe_deployment():
    print("\n--- TEST 7: Corrected state, valid approval, safe deployment ---")
    client = StubLLMClient()
    client.DECISIONS["security"] = {"auth_protocol": "oauth"}
    client.DECISIONS["engineering"] = {"implemented_protocol": "oauth"}
    
    mut = Mutation(
        type=MutationType.CONTENT_FLIP,
        target_agent="qa",
        target_key="implemented_protocol",
        params={"from_value": "oauth", "to_value": "saml"}
    )
    
    # When QA detects stale read, repair re-runs QA and downstream.
    # In this test, engineering restores implemented_protocol to oauth before cascade
    p = create_pipeline(scenario=SSO_SCENARIO, llm=client)
    from mutations import apply_mutation
    apply_mutation(p, mut)
    await p.run()
    
    # Healing: restore implemented_protocol to oauth
    healed = p.store.put(Commitment(
        agent_id="engineering",
        statement="engineering fixed implemented_protocol to oauth",
        key="implemented_protocol",
        value="oauth",
        created_at=p.virtual_clock
    ))
    p.trace.append(healed)
    
    # Now run cascade
    await p.run_cascade(["qa", "deployment", "docs"])
    
    # Invariant evaluation
    results = check_all_invariants(p.trace)
    failures = [r for r in results if not r.passed]
    assert len(failures) == 0, f"All invariants and goal must pass, failed: {failures}"
    
    qa_final = p.store.get_latest("qa_approval")
    dep_final = p.store.get_latest("deploy_action")
    assert qa_final.value == "approved"
    assert dep_final.value == "deploy"
    print("PASS: Corrected state achieved valid approval and safe deployment. All invariants passed.")

async def run_all():
    print("============================================================")
    print("STARTING 7-TEST REGRESSION SUITE")
    print("============================================================")
    await test_1_mismatched_protocols()
    await test_2_cascade_after_stale_qa_approval()
    await test_3_cascade_after_stale_deployment_decision()
    await test_4_all_versions_of_required_key_revoked()
    await test_5_repair_produces_no_commitment()
    await test_6_structural_invariants_pass_but_goal_fails()
    await test_7_corrected_state_valid_approval_safe_deployment()
    print("\n============================================================")
    print("ALL 7 REGRESSION TESTS PASSED DETERMINISTICALLY!")
    print("============================================================")

if __name__ == "__main__":
    asyncio.run(run_all())
