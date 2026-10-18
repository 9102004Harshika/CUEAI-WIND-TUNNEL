import unittest
from typing import List
from models import Event, AgentAction, Commitment
from invariants import (
    no_deploy_without_current_approval,
    no_downstream_disagreement,
    no_action_on_revoked_commitment,
    no_duplicate_execution,
    no_blocked_executions,
)

class TestInvariants(unittest.TestCase):

    def dummy_action(self, agent: str, reads: List[str], r_versions: List[int], produces=None, action_type="execute") -> AgentAction:
        return AgentAction(
            agent_id=agent,
            action_type=action_type,
            reads=reads,
            reads_versions=r_versions,
            executed_at=1.0,
            produced_commitment_id=produces,
        )

    def dummy_commit(self, cid: str, key: str, version: int, agent: str, revoked=False, supersedes=None) -> Commitment:
        c = Commitment(agent_id=agent, statement="test", key=key, value="test", created_at=0.5)
        c.id = cid
        c.version = version
        c.revoked = revoked
        c.supersedes = supersedes
        return c

    def test_no_deploy_without_current_approval(self):
        c1 = self.dummy_commit("c1", "qa_approval", 1, "qa")
        
        # Valid deploy
        tr_valid = [c1, self.dummy_action("deployment", ["c1"], [1], action_type="deploy_service")]
        self.assertIsNone(no_deploy_without_current_approval(tr_valid))

        # Stale deploy (v1 read, v2 exists)
        c2 = self.dummy_commit("c2", "qa_approval", 2, "qa")
        tr_stale = [c1, c2, self.dummy_action("deployment", ["c1"], [1], action_type="deploy_service")]
        self.assertIsNotNone(no_deploy_without_current_approval(tr_stale))
        
        # No approval exists, but deployed
        tr_missing = [self.dummy_action("deployment", ["c99"], [1], action_type="deploy_service")]
        self.assertIsNotNone(no_deploy_without_current_approval(tr_missing))

    def test_no_downstream_disagreement(self):
        c_auth = self.dummy_commit("c_auth", "auth_protocol", 1, "security")
        c_auth2 = self.dummy_commit("c_auth2", "auth_protocol", 2, "security")
        c_res = self.dummy_commit("c_impl", "implemented_protocol", 1, "engineering")
        
        tr_valid = [c_auth, self.dummy_action("eng", ["c_auth"], [1], produces="c_impl"), c_res]
        self.assertIsNone(no_downstream_disagreement(tr_valid))

        # Disagreement (produced c_impl based on c_auth v1, but c_auth2 exists and c_impl is active)
        tr_invalid = [c_auth, self.dummy_action("eng", ["c_auth"], [1], produces="c_impl"), c_res, c_auth2]
        self.assertIsNotNone(no_downstream_disagreement(tr_invalid))

    def test_no_action_on_revoked_commitment(self):
        c1 = self.dummy_commit("c1", "auth", 1, "security")
        c1_revoked = self.dummy_commit("c1", "auth", 1, "security", revoked=True)
        c1_revoked.created_at = 0.5

        # Action reads c1 validly
        valid_act = AgentAction(agent_id="eng", action_type="execute", reads=["c1"], reads_versions=[1], executed_at=0.8)
        self.assertIsNone(no_action_on_revoked_commitment([c1, valid_act]))

        # Action reads c1 AFTER it was revoked
        invalid_act = AgentAction(agent_id="eng", action_type="execute", reads=["c1"], reads_versions=[1], executed_at=0.8)
        self.assertIsNotNone(no_action_on_revoked_commitment([c1_revoked, invalid_act]))

    def test_no_duplicate_execution(self):
        a1 = self.dummy_action("docs", ["c1"], [1])
        self.assertIsNone(no_duplicate_execution([a1]))
        
        # Exact same action type & read sets
        self.assertIsNotNone(no_duplicate_execution([a1, a1]))
        
        # Different read sets (e.g. read v2 instead of v1)
        a2 = self.dummy_action("docs", ["c1"], [2])
        self.assertIsNone(no_duplicate_execution([a1, a2]))

    def test_no_blocked_executions(self):
        a1 = self.dummy_action("qa", [], [], action_type="execute")
        self.assertIsNone(no_blocked_executions([a1]))

        a_blocked = self.dummy_action("deployment", [], [], action_type="execution_blocked")
        a_blocked.payload = {"reason": "missing foo"}
        self.assertIsNotNone(no_blocked_executions([a_blocked]))

if __name__ == '__main__':
    unittest.main()
