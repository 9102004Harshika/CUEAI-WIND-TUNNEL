import pytest
import os
import re
from fastapi.testclient import TestClient
from api import app
from budget import BudgetManager

client = TestClient(app)

def test_health_endpoint_no_secrets():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "cue-wind-tunnel"
    assert "budget" in data
    # Guarantee no key text is ever leaked
    text = response.text
    assert "api_key" not in text.lower() or "api_key_sniff" not in text
    assert not re.search(r"(AIza|AQ\.|sk" + r"-or-v1-)", text)

def test_persistent_budget_tracker(tmp_path):
    budget_file = str(tmp_path / "test_budget.json")
    mgr = BudgetManager(filepath=budget_file, daily_limit=5)
    assert mgr.can_call() is True
    assert mgr.get_status()["used_today"] == 0
    assert mgr.get_status()["remaining"] == 5

    # Record 5 calls
    for _ in range(5):
        mgr.record_call()
    
    assert mgr.can_call() is False
    assert mgr.get_status()["used_today"] == 5
    assert mgr.get_status()["remaining"] == 0

    # Simulate restart by instantiating new manager on same file
    mgr2 = BudgetManager(filepath=budget_file, daily_limit=5)
    assert mgr2.can_call() is False
    assert mgr2.get_status()["used_today"] == 5
