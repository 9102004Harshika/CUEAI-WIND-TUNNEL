# CUE Wind Tunnel: Multi-Agent Stress Testing & Invariant Verification

[![Google Cloud Run](https://img.shields.io/badge/Google%20Cloud-Cloud%20Run-blue?logo=googlecloud)](https://cue-wind-tunnel-139740810303.asia-south1.run.app/)
[![Gemini](https://img.shields.io/badge/Gemini-3.1%20Flash--Lite-orange?logo=googlegemini)](https://ai.google.dev/)
[![Status](https://img.shields.io/badge/Status-Live-success)](https://cue-wind-tunnel-139740810303.asia-south1.run.app/)

> **Live Production Deployment**: [https://cue-wind-tunnel-139740810303.asia-south1.run.app/](https://cue-wind-tunnel-139740810303.asia-south1.run.app/)

---

## 1. The Problem

**When AI agents work as a team, each agent can be individually correct while the team as a whole fails.**

Modern multi-agent architectures introduce asynchronous communication races, stale read states, and duplicate side effects that traditional single-agent evals cannot detect:
- An agent makes a decision based on a protocol version that was invalidated mid-flight by another authority agent.
- A deployment agent executes a duplicate destructive action because identical events were delivered twice without idempotency gates.
- When failure occurs in production, pinpointing the root-cause agent across hundreds of trace events is noisy, slow, and non-deterministic.

---

## 2. What CUE Wind Tunnel Does

CUE Wind Tunnel is an automated stress-testing and invariant verification engine for multi-agent workflows. It follows a 5-step methodology:

1. **Break**: Injects deterministic synthetic mutations (stale reads, duplicate actions, state commit delays, dropped payloads) into multi-agent message buses.
2. **Detect**: Evaluates formal safety and liveness invariants against discrete execution traces without relying on LLM self-evaluation.
3. **Attribute**: Identifies the exact culprit agent and causal dependency chain purely from trace topology.
4. **Try Repair**: Simulates topological re-execution of affected readers and downstream dependencies in a sandbox.
5. **Verify**: Verifies whether the repair safely resolves the violation or if it must be declined (e.g. duplicate side effects with non-idempotent history).

> **Core Philosophy**: Verdicts, attribution, and repair safety come strictly from **deterministic code and formal invariants**, never from generative hallucination.

---

## 3. How Gemini & Google Cloud Run Are Used

### Google Gemini (Gemini 3.1 Flash-Lite)
- **Natural Language Root-Cause Explanation**: Powers /api/explain to provide 3-sentence incident summaries grounded strictly in structured causal facts and trace events.
- **Optional Live Agent Execution**: In the Test Lab and Team Builder, users can toggle specific agents from deterministic stubs to live Gemini reasoning agents to test how LLMs react under live race conditions.
- **Quota Safeguard**: Governed by an automated server-side quota budget manager (250 calls/day), tracked in real time on the live header.

### Google Cloud Run
- **Serverless Production Container**: Hosted on Google Cloud Run in sia-south1 (cueai-501417).
- **Single-Concurrency Control**: Configured with utoscaling.knative.dev/maxScale: '1' and --no-cpu-throttling to ensure simulation deterministic state consistency and zero race conditions during live evaluations.
- **Scale-to-Zero Efficiency**: Fully serverless container scaling to 0 when idle to optimize resource efficiency.

---

## 4. Key Capabilities & Interfaces

1. **Guided Demo (Live Simulator)**:
   - Walk through realistic multi-agent incident scenarios (e.g. SSO Rollout Protocol Race, Duplicate Deployment Action).
   - Interactive pipeline topology with step-by-step state progression and live trace timeline.
2. **Test Lab**:
   - Stress-test multi-agent pipelines (SSO Rollout, Customer Refund Pipeline).
   - Inject targeted mutations (flip decision after read, duplicate delivery, tick delays) or run Monte Carlo live searches to discover edge-case counterexamples.
3. **Team Builder**:
   - Assemble custom 2–8 agent pipelines with defined read/write permissions, state transition operators, and domain invariants.
   - Run verification sandbox and validate compliance before deployment.

---

## 5. How to Run Locally

### Prerequisites
- Python 3.10+
- Node.js 18+ & npm
- (Optional) GEMINI_API_KEY for live LLM explanations and live agent toggles.

### 1. Clone Repository
`ash
git clone https://github.com/9102004Harshika/CUEAI-WIND-TUNNEL.git
cd CUEAI-WIND-TUNNEL
`

### 2. Backend Setup
`ash
cd backend
pip install -r requirements.txt

# (Optional) Export Gemini API Key
# export GEMINI_API_KEY="your-api-key"

uvicorn api:app --reload --port 8000
`
Backend will be live at http://localhost:8000. Test health at http://localhost:8000/api/health.

### 3. Frontend Setup
`ash
cd ../frontend
npm install
npm run dev
`
Open http://localhost:5173 in your browser.

---

## 6. Known Limits & Roadmap

- **Deterministic by Default**: Pipeline agents run as fast, reproducible deterministic stubs by default. Live Gemini runs are capped at 12 calls per simulation to protect quotas.
- **Simulated Repairs**: Re-execution is currently sandbox-simulated; real-world side effects require idempotent compensation workflows (roadmap).
- **Roadmap Features**:
  - Bring-Your-Own (BYO) OpenTelemetry trace upload and validator.
  - Custom YAML safety rule authoring UI.
  - Automated CI/CD regression test ship report generator.

---

## License
MIT License. Built for the Google AI Builder Cup.
