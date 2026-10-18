"""
Tests for Phase 1 and Phase 2:
1. Pure trace graph attribution (never derives culprit by parsing violation strings).
2. Trace ingestion & LangGraph adapter.
3. Replay roundtrip on saved counterexamples.
4. Accepted repair path heals state and restores all invariants.
5. Declined repair path immediately declines duplicates with precise reason.
6. Deterministic simulation reproducibility: same seed gives identical trace.
"""

import pytest
import json
import os
from models import Commitment, AgentAction, Mutation, MutationType
from scenarios import SSO_SCENARIO
from invariants import check_all_invariants
from attribution import derive_attribution
from trace_ingestion import IngestedTracePayload, evaluate_ingested_trace, adapt_langgraph_log
from repair_engine import evaluate_repair
from pipeline import create_pipeline
from mutations import apply_mutation
from run_pipeline import serialize_trace

@pytest.mark.asyncio
async def test_pure_trace_attribution_stale_read():
    # Setup trace: Security commits v1, Eng reads v1, Security updates to v2, Eng acts
    c1 = Commitment(id="c1", agent_id="security", statement="OAuth", key="auth_protocol", value="oauth", version=1, created_at=1.0)
    c2 = Commitment(id="c2", agent_id="security", statement="SAML", key="auth_protocol", value="saml", version=2, created_at=2.0)
    a1 = AgentAction(agent_id="engineering", action_type="implement", reads=["c1"], reads_versions=[1], executed_at=2.5)

    trace = [c1, c2, a1]
    attr = derive_attribution(trace, "no_downstream_disagreement")

    # Change source must be security (wrote v2), stale reader must be engineering
    assert attr.change_source == "security"
    assert "engineering" in attr.stale_readers
    assert attr.target_key == "auth_protocol"
    assert attr.stale_version_read == 1
    assert attr.latest_version == 2

@pytest.mark.asyncio
async def test_pure_trace_attribution_duplicate():
    a1 = AgentAction(agent_id="deployment", action_type="deploy_service", reads=["c1"], reads_versions=[1], executed_at=1.0)
    a2 = AgentAction(agent_id="deployment", action_type="deploy_service", reads=["c1"], reads_versions=[1], executed_at=1.5)

    trace = [a1, a2]
    attr = derive_attribution(trace, "no_duplicate_execution")
    assert attr.change_source == "deployment"
    assert attr.duplicate_executor == "deployment"

def test_trace_ingestion_and_langgraph_adapter():
    langgraph_logs = [
        {"node": "researcher", "writes": {"query_result": "found_docs"}, "reads": [], "time": 1.0},
        {"node": "writer", "writes": {"summary": "done"}, "reads": ["query_result"], "time": 2.0}
    ]
    payload = IngestedTracePayload(
        version="cue.trace.v1",
        format="langgraph",
        source_description="LangGraph Multi-Agent Run",
        events=langgraph_logs
    )
    result = evaluate_ingested_trace(payload)
    assert result["event_count"] == 4 # 2 commitments + 2 actions
    assert result["invariants_checked"] > 0
    assert result["mode"] == "ingested_trace_analysis"

@pytest.mark.asyncio
async def test_accepted_repair_path():
    # Load canonical stale-read counterexample
    filepath = os.path.join(os.path.dirname(__file__), "counterexamples", "counterexample_stale_read.json")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    mutations = [Mutation(**m) for m in data["mutations"]]
    verdict = await evaluate_repair(mutations, scenario=SSO_SCENARIO)
    
    assert verdict.status == "ACCEPTED"
    assert verdict.all_passed_after is True
    assert len(verdict.residual_violations) == 0
    assert "re-running stale reader" in verdict.reason

@pytest.mark.asyncio
async def test_declined_repair_path():
    # Load canonical duplicate counterexample
    filepath = os.path.join(os.path.dirname(__file__), "counterexamples", "counterexample_duplicate.json")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    mutations = [Mutation(**m) for m in data["mutations"]]
    verdict = await evaluate_repair(mutations, scenario=SSO_SCENARIO)

    assert verdict.status == "DECLINED"
    assert verdict.all_passed_after is False
    assert "Duplicate execution already occurred" in verdict.reason

def canonicalize_trace(serialized_trace):
    id_map = {}
    c_c = 0
    a_c = 0
    for e in serialized_trace:
        eid = e.get("id")
        if e.get("event_type") == "commitment":
            if eid not in id_map:
                id_map[eid] = f"c_{c_c}"
                c_c += 1
        else:
            if eid not in id_map:
                id_map[eid] = f"a_{a_c}"
                a_c += 1
    canonical = []
    for e in serialized_trace:
        d = e.copy()
        d["id"] = id_map.get(d.get("id"), d.get("id"))
        if d.get("supersedes"):
            d["supersedes"] = id_map.get(d["supersedes"], d["supersedes"])
        if d.get("produced_commitment_id"):
            d["produced_commitment_id"] = id_map.get(d["produced_commitment_id"], d["produced_commitment_id"])
        if "reads" in d:
            d["reads"] = [id_map.get(r, r) for r in d["reads"]]
        canonical.append(d)
    return canonical

@pytest.mark.asyncio
async def test_deterministic_reproducibility():
    # Same seed and mutation applied to two distinct pipelines produces canonical byte-for-byte identical trace
    m = Mutation(type=MutationType.DELAY, target_agent="engineering", params={"delay_seconds": 3})
    
    p1 = create_pipeline(scenario=SSO_SCENARIO)
    apply_mutation(p1, m)
    trace1 = await p1.run()
    c1 = canonicalize_trace(serialize_trace(trace1))
    s1 = json.dumps(c1, sort_keys=True)

    p2 = create_pipeline(scenario=SSO_SCENARIO)
    apply_mutation(p2, m)
    trace2 = await p2.run()
    c2 = canonicalize_trace(serialize_trace(trace2))
    s2 = json.dumps(c2, sort_keys=True)

    # Assert canonical identical trace
    assert s1 == s2

