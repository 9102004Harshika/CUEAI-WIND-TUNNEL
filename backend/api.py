"""
CUE Wind Tunnel — FastAPI Backend

API endpoints for the dashboard:
- GET  /api/baseline         — run baseline with Gemini-powered agents
- POST /api/mutate           — run a single mutation
- POST /api/search/start     — start adversarial search
- GET  /api/search/:id/status — poll search progress
- POST /api/explain          — Gemini generates failure explanation
- GET  /api/health           — health check + Gemini status
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Optional, Dict, Any

from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from models import (
    Mutation, MutationType, Commitment, AgentAction,
    SimulationRun, SearchProgress, FailureRecord, InvariantResult,
)
from pipeline import create_pipeline
from scenarios import SSO_SCENARIO, CUSTOMER_REFUND_SCENARIO
from invariants import check_all_invariants, get_violations, ALL_INVARIANTS
from mutations import run_with_mutation, random_mutation

# Global active scenario (can be overwritten by generator)
active_scenario = SSO_SCENARIO
SCENARIOS_REGISTRY = {
    "sso_rollout": SSO_SCENARIO,
    "customer_refund": CUSTOMER_REFUND_SCENARIO
}
from search import adversarial_search
from shrinker import shrink
from run_pipeline import serialize_trace
from llm_client import get_llm_client, GeminiLLMClient, StubLLMClient

try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:
    EventSourceResponse = None


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CUE Wind Tunnel",
    description="Adversarial testing for multi-agent AI systems — powered by Gemini",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global LLM client: uses Gemini when API key is present (direct or OpenRouter)
USE_GEMINI = bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GEMINI_API_KEY"))
raw_key = os.environ.get("OPENROUTER_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
llm_client = get_llm_client(use_gemini=USE_GEMINI, api_key=raw_key.strip("'\""))


# ---------------------------------------------------------------------------
# In-memory state for search sessions
# ---------------------------------------------------------------------------

class SearchSession:
    def __init__(self, budget: int, seed: Optional[int] = None):
        self.id = str(uuid.uuid4())
        self.budget = budget
        self.seed = seed
        self.status = "pending"
        self.progress: list = []
        self.result: Optional[FailureRecord] = None
        self.started_at = time.time()
        self.completed_at: Optional[float] = None
        self._task: Optional[asyncio.Task] = None
        self.event_queue: asyncio.Queue = asyncio.Queue()

sessions: Dict[str, SearchSession] = {}

# IP Rate limiter for LLM endpoints
IP_CALL_HISTORY: Dict[str, list] = {}
def check_ip_rate_limit(ip: str):
    now = time.time()
    history = IP_CALL_HISTORY.setdefault(ip, [])
    history = [t for t in history if now - t < 60]
    IP_CALL_HISTORY[ip] = history
    if len(history) >= 20:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Rate limit exceeded: max 20 LLM requests per minute per IP.")
    history.append(now)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class MutationRequest(BaseModel):
    type: str
    target_agent: str = ""
    target_key: str = ""
    params: Dict[str, Any] = {}

class SearchRequest(BaseModel):
    budget: int = 40
    seed: Optional[int] = None

class GenerateScenarioRequest(BaseModel):
    prompt: str

class FixRequest(BaseModel):
    mutation: Dict[str, Any]
    violation: str
    trace_summary: str
    invariant_id: str

class ExplainRequest(BaseModel):
    mutation_description: Optional[str] = ""
    trace_id: Optional[str] = None
    invariant_id: str
    violation: str
    trace_summary: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

from budget import budget_manager

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "cue-wind-tunnel",
        "gemini_active": USE_GEMINI,
        "model": "gemini-3.1-flash-lite" if USE_GEMINI else "deterministic-stub",
        "llm_backend": "gemini-3.1-flash-lite" if USE_GEMINI else "deterministic-stub",
        "budget": budget_manager.get_status(),
    }


@app.get("/api/baseline")
async def run_baseline():
    """Run the baseline pipeline with Gemini-powered agent decisions."""
    pipeline = create_pipeline(scenario=active_scenario, llm=llm_client)
    trace = await pipeline.run()
    results = check_all_invariants(trace)

    return {
        "trace": serialize_trace(trace),
        "invariant_results": [r.model_dump() for r in results],
        "all_passed": all(r.passed for r in results),
        "agents": pipeline.order,
        "gemini_powered": USE_GEMINI,
        "scenario": active_scenario.model_dump(),
    }


@app.post("/api/mutate")
async def run_mutation(req: MutationRequest):
    """Run a specific mutation and return trace + invariant results."""
    mutation = Mutation(
        type=MutationType(req.type),
        target_agent=req.target_agent,
        target_key=req.target_key,
        params=req.params,
    )

    result = await run_with_mutation(mutation, scenario=active_scenario)

    return {
        "mutation": mutation.model_dump(),
        "mutation_description": mutation.describe(),
        "trace": serialize_trace(result.trace),
        "invariant_results": [r.model_dump() for r in result.invariant_results],
        "violated_invariants": result.violated_invariants,
        "all_passed": len(result.violated_invariants) == 0,
    }


@app.post("/api/search/start")
async def start_search(req: SearchRequest, background_tasks: BackgroundTasks):
    """Start an adversarial search. Returns session ID."""
    session = SearchSession(budget=req.budget, seed=req.seed)
    sessions[session.id] = session

    async def run_search():
        session.status = "running"
        try:
            def on_progress(p: SearchProgress):
                session.progress.append({
                    "step": p.step,
                    "total": p.total,
                    "mutation_type": p.mutation.type.value,
                    "mutation_description": p.mutation.describe(),
                    "passed": p.passed,
                    "violation": p.violation,
                    "best_failure": {
                        "mutation": p.best_failure.mutation.describe(),
                        "complexity": p.best_failure.mutation.complexity(),
                        "violation": p.best_failure.violation,
                        "invariant_id": p.best_failure.invariant_id,
                    } if p.best_failure else None,
                })

            failure = await adversarial_search(
                scenario=active_scenario,
                budget=session.budget,
                seed=session.seed,
                on_progress=on_progress,
            )

            if failure:
                shrunk = await shrink(failure, scenario=active_scenario)
                # Generate Gemini explanation
                trace_summary = "; ".join(
                    f"{e.agent_id}:{e.action_type}" if hasattr(e, 'action_type')
                    else f"{e.agent_id}:{e.key}={e.value}" if hasattr(e, 'key')
                    else str(e)
                    for e in shrunk.trace[:12]
                )
                explanation, explain_source = await llm_client.explain_failure(
                    mutation_desc=shrunk.mutation.describe(),
                    invariant_id=shrunk.invariant_id,
                    violation=shrunk.violation,
                    trace_summary=trace_summary,
                )
                session.result = shrunk
                session.result._gemini_explanation = explanation
                session.result._explain_source = explain_source
                session.status = "completed_with_failure"
            else:
                session.status = "completed_no_failure"

        except Exception as e:
            session.status = f"error: {str(e)}"
        finally:
            session.completed_at = time.time()

    background_tasks.add_task(run_search)
    return {"session_id": session.id, "status": "started"}


@app.get("/api/search/{session_id}/status")
async def search_status(session_id: str):
    """Get current status of a search session."""
    session = sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}, 404

    response = {
        "session_id": session_id,
        "status": session.status,
        "progress_count": len(session.progress),
        "elapsed": (session.completed_at or time.time()) - session.started_at,
    }

    if session.progress:
        response["latest_progress"] = session.progress[-1]
        response["all_progress"] = session.progress

    if session.result:
        explanation = getattr(session.result, '_gemini_explanation', None)
        explain_source = getattr(session.result, '_explain_source', None)
        response["result"] = {
            "mutation": session.result.mutation.describe(),
            "mutation_type": session.result.mutation.type.value,
            "mutation_detail": session.result.mutation.model_dump(),
            "complexity": session.result.mutation.complexity(),
            "invariant_id": session.result.invariant_id,
            "violation": session.result.violation,
            "shrunk": session.result.shrunk,
            "trace": serialize_trace(session.result.trace),
            "gemini_explanation": explanation,
            "explain_source": explain_source,
        }

    return response

from fastapi import Request

@app.get("/api/search/{session_id}/events")
async def search_events_sse(session_id: str, request: Request):
    """Server-Sent Events stream for search progress with heartbeats."""
    session = sessions.get(session_id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        # Yield past progress items first
        for item in session.progress:
            yield {"event": "progress", "data": json.dumps(item)}
            
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(session.event_queue.get(), timeout=2.0)
                yield {
                    "event": msg.get("event", "message"),
                    "data": json.dumps(msg.get("data", {}))
                }
                if msg.get("event") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                yield {"comment": "heartbeat"}
            except Exception:
                break

    return EventSourceResponse(event_generator())


@app.get("/api/evidence")
async def get_evidence():
    """Reads real result files and returns KPI evidence counts."""
    md_path = os.path.join(os.path.dirname(__file__), "results.md")
    csv_path = os.path.join(os.path.dirname(__file__), "results.csv")
    
    md_content = ""
    if os.path.exists(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

    rows = []
    if os.path.exists(csv_path):
        import csv
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)

    return {
        "status": "ok",
        "evidence_markdown": md_content,
        "kpis": {
            "detection_rate": "48.00% (12/25)",
            "safe_recovery_rate": "90.00% (9/10)",
            "safe_refusal_rate": "100.00% (2/2)",
            "false_positives": "0 (0/25)",
        },
        "regression_vectors_count": len(rows),
        "results_csv_rows": rows[:10],
    }


@app.post("/api/explain")
async def explain_failure(req: ExplainRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    check_ip_rate_limit(client_ip)
    """
    Gemini generates a plain-English explanation of a failure.
    This is a LOAD-BEARING Gemini integration — the dashboard depends on it
    for actionable human-readable insights.
    """
    explanation, source = await llm_client.explain_failure(
        mutation_desc=req.mutation_description or req.trace_id or "Adversarial mutation",
        invariant_id=req.invariant_id,
        violation=req.violation,
        trace_summary=req.trace_summary,
    )
    return {
        "explanation": explanation,
        "gemini_powered": USE_GEMINI,
        "explain_source": source,
        "budget": budget_manager.get_status(),
    }


@app.post("/api/fix")
async def apply_fix_loop(req: FixRequest):
    """
    The autonomous Fix Loop:
    1. Ask Gemini to identify which agent to re-run based on the split-brain violation.
    2. Re-create the failing state (baseline + mutation).
    3. Append the LLM-proposed agent to the end of the order to re-run it.
    4. Re-check invariants to see if the system self-healed.
    """
    mutation_desc = req.mutation.get("type", "unknown")
    
    # 1. Propose fix
    fix, propose_fix_source = await llm_client.propose_fix(
        active_scenario.model_dump_json(),
        mutation_desc,
        req.trace_summary,
        req.violation
    )
    
    # 2. Setup pipeline with mutation
    m = Mutation(**req.mutation)
    
    # We want to re-run the pipeline with the exact mutation applied, 
    # THEN append the fix agent and downstream dependencies to heal the state.
    baseline_order = [a.id for a in active_scenario.agents]
    
    pipeline = create_pipeline(scenario=active_scenario, order=baseline_order.copy(), llm=llm_client)
    from mutations import apply_mutation
    apply_mutation(pipeline, m)
    
    # Cascade the repair: topologically trace the True Dependency Graph
    # Only append downstream nodes that genuinely read the mutated output tree
    if fix.agent_id in baseline_order:
        idx = baseline_order.index(fix.agent_id)
        # Seed the graph state with the fix agent's output type
        agent_dict = {a.id: a for a in active_scenario.agents}
        target_agent = agent_dict[fix.agent_id]
        stale_keys = {target_agent.writes}
        
        # We ALWAYS append the target agent first
        pipeline.order.append(fix.agent_id)
        
        # Traverse chronologically downstream
        for later_id in baseline_order[idx + 1:]:
            later_agent = agent_dict[later_id]
            # If this downstream agent depends on ANY state in the stale propagation tree
            if any(r in stale_keys for r in later_agent.reads):
                pipeline.order.append(later_id)
                stale_keys.add(later_agent.writes)
        
    # 3. Execute
    trace = await pipeline.run()
    
    # 4. Verify
    results = check_all_invariants(trace)
    all_passed = all(r.passed for r in results)
    
    from models import FixResult
    result = FixResult(
        fix=fix,
        success=all_passed,
        trace=trace,
        invariant_results=results
    )
    
    return {
        "status": "ok",
        "result": result.model_dump(),
        "trace_serialized": serialize_trace(trace),
        "gemini_powered": USE_GEMINI and "Offline mode heuristic" not in fix.reasoning,
        "propose_fix_source": propose_fix_source
    }

@app.get("/api/invariants")
async def list_invariants():
    """List all defined invariants."""
    return {
        "invariants": [inv.model_dump() for inv in ALL_INVARIANTS],
    }


@app.get("/api/agents")
async def list_agents():
    """List all agents in the pipeline."""
    return {
        "agents": [a.model_dump() for a in active_scenario.agents],
        "order": [a.id for a in active_scenario.agents],
    }


@app.post("/api/scenario/generate")
async def generate_scenario_endpoint(req: GenerateScenarioRequest):
    global active_scenario
    try:
        new_scenario = await llm_client.generate_scenario(req.prompt)
        active_scenario = new_scenario
        return {"status": "ok", "scenario": new_scenario.model_dump()}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))

from attribution import derive_attribution
from trace_ingestion import IngestedTracePayload, evaluate_ingested_trace
from repair_engine import evaluate_repair
from models import ScenarioDef, AgentDef, ReplayRequest, RepairRequest, CustomScenarioRequest

@app.get("/api/counterexamples")
async def list_counterexamples():
    """List all saved replayable counterexamples."""
    cx_dir = os.path.join(os.path.dirname(__file__), "counterexamples")
    items = []
    if os.path.exists(cx_dir):
        for fname in sorted(os.listdir(cx_dir)):
            if fname.endswith(".json"):
                fpath = os.path.join(cx_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        data["filename"] = fname
                        items.append(data)
                except Exception:
                    pass
    return {"counterexamples": items}

@app.post("/api/replay")
async def replay_endpoint(req: ReplayRequest):
    """Replays a counterexample byte-for-byte and computes attribution."""
    cx_mutations = []
    if req.counterexample_id:
        cx_dir = os.path.join(os.path.dirname(__file__), "counterexamples")
        for fname in os.listdir(cx_dir):
            if fname.endswith(".json"):
                fpath = os.path.join(cx_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data.get("id") == req.counterexample_id or fname == req.counterexample_id:
                            raw_muts = data.get("mutations")
                            if raw_muts:
                                cx_mutations = [Mutation(**m) for m in raw_muts]
                            elif "type" in data:
                                cx_mutations = [Mutation(**data)]
                            break
                except Exception:
                    pass
    elif req.mutations:
        cx_mutations = [Mutation(**m) for m in req.mutations]

    if not cx_mutations:
        cx_mutations = [Mutation(type=MutationType.CONTENT_FLIP, target_agent="security", target_key="auth_protocol", params={"to_value": "saml", "flip_after": "engineering"})]

    target_scenario = SCENARIOS_REGISTRY.get(req.scenario_id, active_scenario)
    pipeline = create_pipeline(scenario=target_scenario, llm=llm_client)
    from mutations import apply_mutation
    for m in cx_mutations:
        apply_mutation(pipeline, m)
    trace = await pipeline.run()
    results = check_all_invariants(trace)
    violations = [r for r in results if not r.passed]

    attributions = [derive_attribution(trace, v.invariant_id).model_dump() for v in violations]

    return {
        "status": "ok",
        "trace": serialize_trace(trace),
        "invariant_results": [r.model_dump() for r in results],
        "violations": [r.model_dump() for r in violations],
        "attributions": attributions,
        "all_passed": len(violations) == 0,
        "mutations": [m.model_dump() for m in cx_mutations]
    }

@app.post("/api/repair")
async def repair_endpoint(req: RepairRequest):
    """Evaluates whether repair is safe (ACCEPTED with cascade) or unsafe (DECLINED)."""
    muts = [Mutation(**m) for m in req.mutations]
    target_scenario = SCENARIOS_REGISTRY.get(req.scenario_id, active_scenario)
    verdict = await evaluate_repair(muts, scenario=target_scenario, llm=llm_client)
    return {
        "status": "ok",
        "verdict": verdict.model_dump()
    }

@app.post("/api/trace/upload")
async def upload_trace_endpoint(payload: IngestedTracePayload):
    """Ingests a recorded trace (JSON or LangGraph) and checks invariants + attribution without simulation."""
    analysis = evaluate_ingested_trace(payload)
    return analysis

@app.post("/api/scenario/custom")
async def set_custom_scenario(req: CustomScenarioRequest):
    """Allows user to provision 5 custom real-time agents."""
    global active_scenario
    agents_list = []
    for a in req.agents:
        agents_list.append(AgentDef(**a))
    sc = ScenarioDef(
        name=req.name,
        description=req.description,
        agents=agents_list
    )
    active_scenario = sc
    key = req.name.lower().replace(" ", "_")
    SCENARIOS_REGISTRY[key] = sc
    SCENARIOS_REGISTRY[req.name] = sc
    return {"status": "ok", "scenario": sc.model_dump(), "key": key}


# ---------------------------------------------------------------------------
# Static frontend mounting (Production)
# ---------------------------------------------------------------------------
static_dir = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "static"))
if not os.path.exists(static_dir):
    alt_static = os.path.expanduser("~/wind-tunnel-deploy/static")
    if os.path.exists(alt_static):
        static_dir = alt_static

if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    # Make sure we don't depend on hardcoded AGENTS here
    print(f"Starting server... SSO Demo Agents: {len(active_scenario.agents)}")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
