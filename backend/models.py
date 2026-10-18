"""
CUE Wind Tunnel — Core Data Models

Every agent action is a structured event. This is the spine of the whole system.
"""

from __future__ import annotations

import uuid
import time
from typing import Optional, List, Union, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MutationType(str, Enum):
    DELAY = "delay"
    REORDER = "reorder"
    REVOKE = "revoke"
    DUPLICATE = "duplicate"
    CONTENT_FLIP = "content_flip"


# ---------------------------------------------------------------------------
# Core event models
# ---------------------------------------------------------------------------

class Commitment(BaseModel):
    """A structured decision / fact produced by an agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    statement: str                          # human-readable, for the demo UI
    key: str                                # normalized fact key, e.g. "auth_protocol"
    value: str                              # e.g. "oauth", "saml", "approved"
    version: int = 1                        # monotonically increasing per key
    created_at: float = Field(default_factory=time.time)
    supersedes: Optional[str] = None        # id of the commitment this replaces
    revoked: bool = False
    revoked_at: Optional[float] = None

    @property
    def event_type(self) -> str:
        return "commitment"


class ExplainRequest(BaseModel):
    mutation_description: Optional[str] = ""
    invariant_id: str
    violation: str
    trace_summary: str = ""

# ---------------------------------------------------------------------------
# Repair Loop Models
# ---------------------------------------------------------------------------

class AgentFix(BaseModel):
    """A proposed autonomous fix action."""
    agent_id: str
    reasoning: str

class FixResult(BaseModel):
    """The result of applying a fix."""
    fix: AgentFix
    success: bool
    trace: List[Event]
    invariant_results: List[InvariantResult]


class AgentDef(BaseModel):
    id: str
    name: str
    role: str
    reads: List[str]
    writes: str
    allowed_values: List[str]


class ScenarioDef(BaseModel):
    name: str
    description: str
    agents: List[AgentDef]


class AgentAction(BaseModel):
    """A side-effecting action taken by an agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    action_type: str                        # e.g. "execute_refund", "deploy_service"
    reads: List[str] = Field(default_factory=list)           # commitment ids this action depends on
    reads_versions: List[int] = Field(default_factory=list)  # version of each commitment as seen
    produced_commitment_id: Optional[str] = None
    executed_at: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)

    @property
    def event_type(self) -> str:
        return "action"


# Union type for trace events
Event = Union[Commitment, AgentAction]


class Invariant(BaseModel):
    """A property that should hold over every valid trace."""
    id: str
    description: str                        # natural language, shown in UI
    check_fn: str                           # name of a Python function in invariants.py
    scope: List[str] = Field(default_factory=list)  # commitment keys / action types it watches


class InvariantResult(BaseModel):
    """Result of checking one invariant against a trace."""
    invariant_id: str
    invariant_description: str
    passed: bool
    reason: Optional[str] = None            # human-readable explanation on FAIL


# ---------------------------------------------------------------------------
# Mutation & search models
# ---------------------------------------------------------------------------

class Mutation(BaseModel):
    """A single perturbation applied to a pipeline run."""
    type: MutationType
    target_agent: str = ""
    target_key: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)

    def complexity(self) -> float:
        """Smaller = simpler mutation.  Used by the shrinker."""
        base = {
            MutationType.DELAY: 1.0,
            MutationType.REORDER: 2.0,
            MutationType.REVOKE: 3.0,
            MutationType.DUPLICATE: 1.5,
            MutationType.CONTENT_FLIP: 3.0,
        }.get(self.type, 2.0)
        delay = self.params.get("delay_seconds", 0)
        return base + delay * 0.1

    def describe(self) -> str:
        """Plain-English description for the UI."""
        if self.type == MutationType.DELAY:
            secs = self.params.get("delay_seconds", 0)
            return (f"Delay delivery of '{self.target_key}' to "
                    f"{self.target_agent} by {secs}s")
        if self.type == MutationType.REORDER:
            swap = self.params.get("swap_with", "?")
            return (f"Swap execution order: {self.target_agent} ↔ {swap}")
        if self.type == MutationType.REVOKE:
            return (f"Revoke '{self.target_key}' after {self.target_agent} "
                    f"has already read it")
        if self.type == MutationType.DUPLICATE:
            return (f"Deliver '{self.target_key}' twice to {self.target_agent}")
        if self.type == MutationType.CONTENT_FLIP:
            old = self.params.get("from_value", "?")
            new = self.params.get("to_value", "?")
            return (f"Flip '{self.target_key}' from {old}→{new} after "
                    f"{self.target_agent} already read {old}")
        return f"Unknown mutation: {self.type}"


# ---------------------------------------------------------------------------
# Simulation run record
# ---------------------------------------------------------------------------

class SimulationRun(BaseModel):
    """One complete execution of the pipeline (possibly mutated)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scenario: Dict[str, Any] = Field(default_factory=dict)  # the perturbation applied
    mutation: Optional[Mutation] = None
    trace: List[Event] = Field(default_factory=list)
    invariant_results: List[InvariantResult] = Field(default_factory=list)
    violated_invariants: List[str] = Field(default_factory=list)
    minimal: bool = False                   # True if this is a shrunk minimal counterexample


class FailureRecord(BaseModel):
    """A confirmed invariant violation with its mutation and trace."""
    mutation: Mutation
    trace: List[Event] = Field(default_factory=list)
    violation: str                          # human-readable violation description
    invariant_id: str
    shrunk: bool = False


class SearchProgress(BaseModel):
    """Progress update during adversarial search."""
    step: int
    total: int
    mutation: Mutation
    passed: bool
    violation: Optional[str] = None
    best_failure: Optional[FailureRecord] = None


class ReplayRequest(BaseModel):
    counterexample_id: Optional[str] = None
    mutations: Optional[List[Dict[str, Any]]] = None
    scenario_id: Optional[str] = None


class RepairRequest(BaseModel):
    mutations: List[Dict[str, Any]]
    scenario_id: Optional[str] = None


class CustomScenarioRequest(BaseModel):
    name: str
    description: str
    agents: List[Dict[str, Any]]


AgentDef.model_rebuild()
ScenarioDef.model_rebuild()
AgentAction.model_rebuild()
Commitment.model_rebuild()
SimulationRun.model_rebuild()
FailureRecord.model_rebuild()
SearchProgress.model_rebuild()
ReplayRequest.model_rebuild()
RepairRequest.model_rebuild()
CustomScenarioRequest.model_rebuild()
