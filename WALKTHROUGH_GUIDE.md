# CUE Wind Tunnel: Complete Product Walkthrough & Evaluator Guide

> **Live Production Deployment**: [https://cue-wind-tunnel-139740810303.asia-south1.run.app/](https://cue-wind-tunnel-139740810303.asia-south1.run.app/)  
> **GitHub Repository**: [https://github.com/9102004Harshika/CUEAI-WIND-TUNNEL](https://github.com/9102004Harshika/CUEAI-WIND-TUNNEL)  
> **Track**: Future of Work & Enterprise Productivity  
> **Team**: CUE AI (Lead: Harshika)

---

## Executive Overview

**The Fundamental Problem**: When autonomous AI agents collaborate as a team, each individual agent can satisfy its local prompt perfectly while the team as a whole fails due to asynchronous race conditions, stale memory reads, and non-idempotent duplicate side effects.

**The Solution**: CUE Wind Tunnel treats multi-agent systems as distributed state machines. Instead of using flaky "LLM-as-a-judge" prompts, CUE implements formal invariant checks, topological causal attribution, and isolated sandbox replay. 

**Core Principle**: **Verdicts and safety bounds come strictly from deterministic code, never from generative model hallucination.**

---

## 1. Guided Demo (Live Simulator Walkthrough)

### Top Header & Live Telemetry
- **`MODEL · gemini-3.1-flash-lite`**: Populated dynamically from `/api/health`, confirming Google Gemini 3.1 Flash-Lite connectivity.
- **`● GEMINI : LIVE`**: Live status heartbeat indicating the GenAI endpoint is responsive.
- **`Gemini calls left today: 248 (2/250 used)`**: Automated quota protection engine (`budget.py`) enforcing a sliding daily cap to prevent quota drain.

---

### Scenario 1: Stale Read & Safe Repair Flow
* **Preset Button**: `▷ Stale read → safe repair` (Selected by default)
* **Subtitle**: *"Security flips auth_protocol to saml right after Docs read it."*

#### Step 1: Normal Baseline (`1. The team works normally`)
- **Action**: Click Step 1.
- **Execution**: Runs the clean baseline trace where all 5 agents (`Security`, `Engineering`, `QA`, `Deployment`, `Docs`) operate in sequence on OAuth.
- **Visual State**:
  - All agent cards display `clean` green status.
  - Trace timeline shows 15 clean events (#0 to #14).
  - Diagnostic card outputs: `no violation`.

#### Step 2: Injected Concurrency Mutation (`2. We break something on purpose`)
- **Action**: Click Step 2.
- **Execution**: Injects an asynchronous protocol race into shared state memory.
- **Visual State**:
  - `Security` agent card highlights in **purple** (mutated: flips `auth_protocol` from `oauth@v1` to `saml@v2`).
  - `Docs` agent card highlights in **cyan** with badge: `ACTED ON STALE v1 (Security wrote v2)`.
  - Discrete trace shows event `#5: security write auth_protocol="saml" @v2` occurring before downstream readers finish.

#### Step 3: Formal Topological Attribution (`3. Cue finds who caused it`)
- **Action**: Click Step 3.
- **Execution**: Evaluates formal freshness invariants and traverses the DAG dependency tree.
- **Visual State**:
  - **WHO CAUSED IT** Card populates:
    - `CHANGE SOURCE: security` (The agent that invalidated the key)
    - `STALE READERS: docs` (The agent that consumed invalidated state)
    - `KEY / VERSIONS: auth_protocol · v1 → v2`
    - CUE Re-run rule: `readers of changed key + downstream agents in topological dependency order`.

#### Step 4: Sandbox Cascading Replay & Safe Repair (`4. Can it be repaired safely?`)
- **Action**: Click Step 4 & Click `Try a simulated repair`.
- **Execution**: Computes the minimal subgraph of affected agents (`engineering`, `qa`, `deployment`, `docs`) and re-executes them in an isolated sandbox.
- **Visual State**:
  - **VERDICT** Card: `Safe repair confirmed`.
  - Re-executing downstream readers restores end-to-end invariant compliance without side-effect conflicts.

#### Feature Spotlight: Gemini 3.1 Flash-Lite Root Cause Explainer
- **Action**: Click the `Explain` button on the right card.
- **Execution**: Calls `/api/explain` with structured causal facts.
- **Visual State**:
  - Button switches to `Querying...`
  - Streams a concise 3-sentence summary: *"Agent security updated auth_protocol to saml while docs had already acted on oauth. The failure was caused by an asynchronous read-modify race condition. CUE successfully verified a safe repair by re-running downstream readers."*
  - Header counter updates in real time (e.g. from `249` to `248`).

---

### Scenario 2: Duplicate Delivery & Declined Repair Flow
* **Preset Button**: `▷ Duplicate action → declined`
* **Subtitle**: *"Deployment ran twice with identical inputs in history."*

#### Step-by-Step Flow:
1. Click `▷ Duplicate action → declined`.
2. Advance stepper to **Step 2**.
3. **Visual State**:
   - `deployment` card highlights in **red** with warning: `DUPLICATE ACTION: Deployment ran twice with identical inputs`.
   - `security`, `engineering`, `qa`, and `docs` remain labeled **stub** and clean green.
   - Trace timeline shows event `#8` and event `#9` with identical action fingerprint `fp=8a71864b433879`.
4. **The Critical Difference**:
   - Look at the **VERDICT** card:
     - Output: `Violation detected · repair evaluated`
     - Formally outputs: `Duplicate action cannot be repaired safely (repair_safe = false)`.
   - **Why This Matters**: Re-running a duplicate write (like charging a credit card or provisioning a server twice) causes catastrophic side-effects. CUE's repair engine formally **declines** the repair and alerts developers that an idempotency key or compensation saga is required.

---

## 2. Test Lab (Stress-Testing & Custom Workflows)

* **Navigation**: Click the **`TEST LAB`** tab in the top navigation.

### Column 1: Team & Agent Execution Modes
- **Team Selector**: Switch between `sso_rollout` and **`customer_refund`** (Customer Refund Pipeline).
- **Customer Refund Swarm**:
  - `Support`: Evaluates customer refund claims (`refund` or `deny`).
  - `Finance`: Mirrors support decision into the ledger.
  - `Compliance`: Evaluates ledger and support decision; approves ONLY if they match.
  - `Payout`: Executes transaction if compliance approves.
  - `Notifications`: Sends customer receipt.
- **Live Gemini Checkboxes**: Option to toggle any agent from a deterministic stub to live Gemini 3.1 Flash-Lite reasoning.

### Column 2: Synthetic Fault Injector
- **Presets**:
  - `+ Flip decision after read`: Injects an asynchronous decision flip right after reading.
  - `+ Deliver message twice`: Injects duplicate network packets.
  - `+ Delay state commitment by 2 ticks`: Injects event lag.
- **Action**: Select `Customer Refund Pipeline` and click `+ Flip decision after read`.

### Column 3: Invariant Evaluation & Counterexample Discovery
- **Action**: Click **`▷ Run team`**.
- **Execution & Verdict** (< 15ms latency):
  - `rules broken: compliance_approval_mismatch`
  - `verdict: Violation detected · repair evaluated`
  - `counterexample: customer_refund_mismatch`
- **Monte Carlo Live Search**:
  - Click **`Run live search`**: Evaluates 25 randomized mutation stacks against the pipeline, highlighting failing edge-case configurations in red.
- **Saved Counterexample Replay**:
  - Click **`⟲ Replay`** on any saved counterexample (`duplicate_deployment`, `stale_flip_security`) to load the exact failure trace into the Guided Demo.

---

## 3. Team Builder (Custom Swarm Architecture)

* **Navigation**: Click the **`TEAM BUILDER`** tab in the top navigation.

### Visual Agent Specification Canvas
- Allows architects to assemble custom **2 to 8 agent swarms** with mathematical safety boundaries:
  - **Reads (keys)**: State variables the agent may consume.
  - **Writes (keys)**: State variables the agent may mutate.
  - **Allowed Values**: Strict enum domains (e.g. `refund, deny`, `approve, reject`).
  - **Operation**: State transition operators (`constant`, `copy`, `approve_if_equal`, `gate_on`).
- **Validation**:
  - Click **`Validate & load team into session`**.
  - Validates topological acyclicity and shared state contracts.
  - Registers the team as `custom_saved_team` and loads it directly into the Test Lab simulation sandbox.

---

## 4. Architectural Rigor & Google Cloud Integration

1. **Google Cloud Run (Compute Layer)**:
   - Hosted in region `asia-south1` (`cueai-501417`).
   - Configured with `autoscaling.knative.dev/maxScale: '1'` and `--no-cpu-throttling` to ensure single-instance determinism and eliminate multi-tenant simulation jitter.
   - Automatically scales to zero when idle for optimal resource efficiency.

2. **Google Gemini 3.1 Flash-Lite (Explainability & Evals)**:
   - Integrated natively via the Google GenAI SDK.
   - High-throughput, sub-second latency for natural language incident summaries.
   - Protected by a server-side daily budget guard (`250 calls/day`).

3. **Google Cloud Firestore (Persistence Layer)**:
   - Stores reproducible counterexamples, agent definitions, and benchmark regression records for replayability.

4. **Empirical Benchmarks (`results.csv`)**:
   - 100 Total Synthetic Benchmark Runs:
     - 20 Duplicates: 20/20 caught & declined
     - 20 Content Flips: 20/20 caught & repaired
     - 20 Delays, 20 Reorders, 20 Drops: Validated clean execution
     - Precision: 100% on designed violations; 0 false positives.
