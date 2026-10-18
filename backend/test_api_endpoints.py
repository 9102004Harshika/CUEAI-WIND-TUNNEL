import pytest
from fastapi.testclient import TestClient
from api import app

client = TestClient(app)

def test_get_counterexamples():
    res = client.get("/api/counterexamples")
    assert res.status_code == 200
    data = res.json()
    assert "counterexamples" in data
    assert len(data["counterexamples"]) > 0

def test_replay_counterexample():
    res = client.post("/api/replay", json={"counterexample_id": "cx-stale-read-01"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "trace" in data
    assert "invariant_results" in data
    assert "attributions" in data
    assert len(data["violations"]) > 0
    # Change source should be security
    assert data["attributions"][0]["change_source"] == "security"

def test_repair_stale_read_accepted():
    mutations = [
        {
            "type": "content_flip",
            "target_agent": "security",
            "target_key": "auth_protocol",
            "params": {"to_value": "saml", "flip_after": "engineering"}
        }
    ]
    res = client.post("/api/repair", json={"mutations": mutations})
    assert res.status_code == 200
    data = res.json()
    assert data["verdict"]["status"] == "ACCEPTED"
    assert data["verdict"]["all_passed_after"] is True

def test_repair_duplicate_declined():
    mutations = [
        {
            "type": "duplicate",
            "target_agent": "deployment",
            "target_key": "deploy_action",
            "params": {}
        }
    ]
    res = client.post("/api/repair", json={"mutations": mutations})
    assert res.status_code == 200
    data = res.json()
    assert data["verdict"]["status"] == "DECLINED"
    assert "Duplicate execution already occurred" in data["verdict"]["reason"]

def test_trace_upload_endpoint():
    payload = {
        "version": "cue.trace.v1",
        "format": "langgraph",
        "source_description": "Production Agent Run",
        "events": [
            {"node": "agent_alpha", "writes": {"plan": "v1"}, "reads": [], "time": 0.1},
            {"node": "agent_beta", "writes": {"code": "v1"}, "reads": ["plan"], "time": 0.2}
        ]
    }
    res = client.post("/api/trace/upload", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["event_count"] == 4
    assert data["invariants_checked"] > 0

def test_custom_scenario_provisioning():
    custom_team = {
        "name": "Finance & Compliance Workflow",
        "description": "5 custom agents auditing expenses",
        "agents": [
            {"id": "intake", "name": "Intake Agent", "role": "Intake invoices", "reads": [], "writes": "invoice_id", "allowed_values": ["inv-101"]},
            {"id": "auditor", "name": "Audit Agent", "role": "Audit invoice", "reads": ["invoice_id"], "writes": "audit_verdict", "allowed_values": ["clean", "flagged"]},
            {"id": "manager", "name": "Manager Agent", "role": "Approval", "reads": ["audit_verdict"], "writes": "mgmt_approval", "allowed_values": ["approved", "rejected"]},
            {"id": "payout", "name": "Payout Agent", "role": "Disburse funds", "reads": ["mgmt_approval"], "writes": "payout_status", "allowed_values": ["disbursed", "blocked"]},
            {"id": "ledger", "name": "Ledger Agent", "role": "Record transaction", "reads": ["payout_status"], "writes": "ledger_entry", "allowed_values": ["recorded"]}
        ]
    }
    res = client.post("/api/scenario/custom", json=custom_team)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert len(data["scenario"]["agents"]) == 5

def test_evidence_endpoint():
    res = client.get("/api/evidence")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "kpis" in data
    assert "detection_rate" in data["kpis"]
    assert "safe_recovery_rate" in data["kpis"]

def test_search_sse_endpoint():
    # Start search
    res = client.post("/api/search/start", json={"budget": 5, "seed": 42})
    assert res.status_code == 200
    session_id = res.json()["session_id"]

    # Read status
    status_res = client.get(f"/api/search/{session_id}/status")
    assert status_res.status_code == 200
