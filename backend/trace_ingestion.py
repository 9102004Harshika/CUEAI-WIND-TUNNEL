"""
CUE Wind Tunnel — Trace Ingestion and Adapters
Allows teams to upload real-world traces (LangGraph, generic JSON, etc.)
and run invariants & attribution WITHOUT running a simulation.
"""

from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, Field, ValidationError
from models import Commitment, AgentAction, Event
from invariants import check_all_invariants
from attribution import derive_attribution, AttributionResult

class RawTraceEvent(BaseModel):
    event_type: str # "commitment" | "action" | "write" | "read"
    agent_id: str
    key: str = ""
    value: str = ""
    version: int = 1
    action_type: str = "execute"
    reads: List[str] = Field(default_factory=list)
    reads_versions: List[int] = Field(default_factory=list)
    timestamp: float = 0.0

class IngestedTracePayload(BaseModel):
    version: str = "cue.trace.v1"
    format: str = "cue_json" # "cue_json" | "langgraph" | "generic_span"
    source_description: str = ""
    events: List[Dict[str, Any]]

def adapt_langgraph_log(raw_logs: List[Dict[str, Any]]) -> List[Event]:
    """
    Adapter converting LangGraph checkpoint/node execution logs into CUE events.
    """
    events: List[Event] = []
    version_tracker: Dict[str, int] = {}

    for idx, node in enumerate(raw_logs):
        agent_id = node.get("node") or node.get("agent_id") or f"agent_{idx}"
        writes = node.get("writes", {})
        reads = node.get("reads", [])
        
        # In LangGraph, each write can be treated as a commitment
        for key, val in writes.items():
            current_v = version_tracker.get(key, 0) + 1
            version_tracker[key] = current_v
            c = Commitment(
                agent_id=agent_id,
                statement=f"{agent_id} wrote {key}={val}",
                key=key,
                value=str(val),
                version=current_v,
                created_at=float(node.get("time", idx))
            )
            events.append(c)

        # Actions representing node execution
        read_versions = [version_tracker.get(r, 1) for r in reads]
        action = AgentAction(
            agent_id=agent_id,
            action_type=node.get("action", "execute_step"),
            reads=reads,
            reads_versions=read_versions,
            executed_at=float(node.get("time", idx)) + 0.05
        )
        events.append(action)

    return events

def parse_and_validate_trace(payload: IngestedTracePayload) -> Tuple[List[Event], List[str]]:
    """
    Validates and normalizes ingested traces into CUE Event models.
    """
    warnings: List[str] = []
    events: List[Event] = []

    if payload.format == "langgraph":
        events = adapt_langgraph_log(payload.events)
        return events, warnings

    for idx, raw in enumerate(payload.events):
        etype = raw.get("event_type", raw.get("type", "commitment"))
        agent = raw.get("agent_id", raw.get("agent", "unknown"))
        
        if etype in ("commitment", "write"):
            key = raw.get("key", "default_key")
            val = str(raw.get("value", ""))
            v = int(raw.get("version", 1))
            c = Commitment(
                agent_id=agent,
                statement=raw.get("statement", f"{agent} committed {key}"),
                key=key,
                value=val,
                version=v,
                created_at=float(raw.get("timestamp", idx))
            )
            events.append(c)
        elif etype in ("action", "read"):
            reads = raw.get("reads", [])
            r_versions = raw.get("reads_versions", [1] * len(reads))
            if not r_versions and reads:
                warnings.append(f"Event index {idx}: missing reads_versions; defaulted to version 1. Attribution may be degraded.")
            act = AgentAction(
                agent_id=agent,
                action_type=raw.get("action_type", "execute"),
                reads=reads,
                reads_versions=r_versions,
                executed_at=float(raw.get("timestamp", idx))
            )
            events.append(act)

    return events, warnings

def evaluate_ingested_trace(payload: IngestedTracePayload) -> Dict[str, Any]:
    """
    Analyzes an ingested trace: evaluates invariants and derives attribution.
    """
    events, warnings = parse_and_validate_trace(payload)
    results = check_all_invariants(events)
    violations = [r for r in results if not r.passed]

    attributions: List[AttributionResult] = []
    for viol in violations:
        attr = derive_attribution(events, viol.invariant_id)
        attributions.append(attr)

    return {
        "event_count": len(events),
        "invariants_checked": len(results),
        "violations_found": len(violations),
        "invariant_results": [r.model_dump() for r in results],
        "attributions": [a.model_dump() for a in attributions],
        "warnings": warnings,
        "mode": "ingested_trace_analysis"
    }
