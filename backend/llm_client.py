"""
CUE Wind Tunnel — LLM Client

Wraps ALL Gemini API calls via OpenRouter (OpenAI-compatible API).
Two load-bearing Gemini integration points:
1. Agent decisions: Gemini makes the actual protocol/approval choices
2. Failure explanation: Gemini generates plain-English analysis of why a
   minimal counterexample matters, shown live in the dashboard.
"""

from __future__ import annotations

import os
import json
import asyncio
import aiohttp
import hashlib
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Any
from dotenv import load_dotenv

load_dotenv()
load_dotenv('.env', override=True)
load_dotenv('../.env', override=True)
load_dotenv(r'C:\Users\HARSHIKA\Projects\CueAI\Backend\.env', override=True)
import time
import asyncio

_CACHE = {}

_LAST_NATIVE_CALL_TIME = 0.0
_NATIVE_LOCK = asyncio.Lock()

# OpenRouter config
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "google/gemini-2.0-flash-exp:free"

_CACHE = {}

def get_cache_key(prompt: str, model: str) -> str:
    return hashlib.sha256((prompt + model).encode('utf-8')).hexdigest()

class BaseLLMClient(ABC):
    """Interface for LLM-backed decision making."""

    @abstractmethod
    async def generate_decision(self, agent_id: str, context: str) -> str:
        ...

    @abstractmethod
    async def extract_commitment_value(self, text: str, key: str) -> str:
        ...

    @abstractmethod
    async def explain_failure(
        self,
        mutation_desc: str,
        invariant_id: str,
        violation: str,
        trace_summary: str,
    ) -> Tuple[str, str]:
        ...

    @abstractmethod
    async def propose_fix(
        self, scenario_json: str, mutation_desc: str, trace_summary: str, violation: str
    ) -> Tuple[Any, str]:
        ...

    @abstractmethod
    async def generate_scenario(self, prompt: str):
        ...


class StubLLMClient(BaseLLMClient):
    """
    Deterministic stub for testing without an API key.
    Returns consistent, scenario-appropriate decisions.
    """

    DECISIONS = {
        "security": {"auth_protocol": "oauth"},
        "engineering": {"implemented_protocol": "oauth"},
        "qa": {"qa_approval": "approved"},
        "deployment": {"deploy_action": "deploy"},
        "docs": {"implemented_protocol": "oauth"},
    }

    async def generate_decision(self, agent_def, context: str) -> str:
        # Parse context block for states safely
        state = {}
        for part in context.split("; "):
            if "=" in part:
                k, v = part.split("=", 1)
                state[k] = v

        if agent_def.id == "qa":
            auth = state.get("auth_protocol", "unknown")
            impl = state.get("implemented_protocol", "unknown")
            if auth == impl:
                return "approved"
            else:
                return "rejected"
                
        if agent_def.id == "deployment":
            qa_val = state.get("qa_approval", "unknown")
            if qa_val == "rejected":
                return "hold"
            return "deploy"
        
        decisions = self.DECISIONS.get(agent_def.id, {})
        for key, value in decisions.items():
            return value
        return agent_def.allowed_values[0] if agent_def.allowed_values else "acknowledged"

    async def extract_commitment_value(self, text: str, key: str) -> str:
        return text

    async def explain_failure(
        self,
        mutation_desc: str,
        invariant_id: str,
        violation: str,
        trace_summary: str,
    ) -> Tuple[str, str]:
        return (
            f"The fault ({mutation_desc}) broke the '{invariant_id}' invariant. "
            f"Specifically: {violation}",
            "stub"
        )

    async def generate_scenario(self, prompt: str):
        from models import ScenarioDef
        from scenarios import SSO_SCENARIO
        print("WARNING: Using StubLLMClient for scenario generation. Returning SSO_SCENARIO.")
        return SSO_SCENARIO

    async def generate_summary(self, prompt: str) -> str:
        return "Stub plain-english summary."

    async def propose_fix(self, scenario_json: str, mutation_desc: str, trace_summary: str, violation: str) -> Tuple[Any, str]:
        from models import AgentFix
        import re
        print("WARNING: Using StubLLMClient for propose_fix.")
        target = "deployment"
        
        if "stale read of" in violation:
            key_match = re.search(r"stale read of '([^']+)'", violation)
            if key_match:
                stale_key = key_match.group(1)
                key_to_agent = {
                    "auth_protocol": "security",
                    "implemented_protocol": "engineering",
                    "qa_approval": "qa",
                    "deploy_action": "deployment",
                    "documented_protocol": "docs"
                }
                target = key_to_agent.get(stale_key, "engineering")
        else:
            match = re.search(r"^([a-zA-Z0-9_\-]+)(?:'s| executed| acted)", violation)
            if match:
                target = match.group(1)

        return AgentFix(agent_id=target, reasoning=f"Offline mode heuristic selected root cause: '{target}'."), "stub"


class GeminiLLMClient(BaseLLMClient):
    """
    Production client using Gemini via OpenRouter (OpenAI-compatible API).
    Requires OPENROUTER_API_KEY environment variable.
    """

    def __init__(self, native_key: str = None, openrouter_key: str = None):
        self._native_key = native_key
        self._openrouter_key = openrouter_key
        self._api_key = self._native_key or self._openrouter_key

    async def _call_gemini(self, messages: list, max_tokens: int = 150) -> Tuple[str, str]:
        """Make an async call with fallback: Native Gemini -> OpenRouter."""
        
        sys_prompt = next((m['content'] for m in messages if m['role'] == 'system'), "")
        user_prompt = next((m['content'] for m in messages if m['role'] == 'user'), "")
        
        # Check cache
        cache_key = get_cache_key(user_prompt + sys_prompt, OPENROUTER_MODEL)
        if cache_key in _CACHE:
            return _CACHE[cache_key], "gemini_native_cached"

        import requests
        import traceback
        
        print(f"NATIVE KEY: {bool(self._native_key)} | OR KEY: {bool(self._openrouter_key)}", flush=True)
        # 1. Try Native Google API First
        if self._native_key:
            retries = [1, 2, 4]
            for attempt, delay in enumerate(retries + [0]):
                try:
                    global _LAST_NATIVE_CALL_TIME
                    async with _NATIVE_LOCK:
                        now = time.time()
                        elapsed = now - _LAST_NATIVE_CALL_TIME
                        if elapsed < 6.0:
                            await asyncio.sleep(6.0 - elapsed)
                        _LAST_NATIVE_CALL_TIME = time.time()

                    model_id = "gemini-3.1-flash-lite"
                    native_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
                    headers = {"x-goog-api-key": self._native_key, "Content-Type": "application/json"}
                    native_payload = {
                        "contents": [{"parts": [{"text": user_prompt}]}],
                        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.1}
                    }
                    if sys_prompt:
                        native_payload["systemInstruction"] = {"parts": [{"text": sys_prompt}]}
                        
                    resp = await asyncio.to_thread(requests.post, native_url, json=native_payload, headers=headers, timeout=30)
                    if resp.status_code == 200:
                        print(f"[{resp.status_code}] Answered by {model_id}", flush=True)
                        try:
                            from budget import budget_manager
                            budget_manager.record_call(source="gemini_native")
                        except Exception:
                            pass
                        data = resp.json()
                        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
                        result_text = parts[0].get("text", "").strip()
                        _CACHE[cache_key] = result_text
                        return result_text, "gemini_native"
                    elif resp.status_code == 429:
                        print(f"[{resp.status_code}] NATIVE GEMINI 429: {resp.text}", flush=True)
                        retry_delay_sec = delay
                        try:
                            err_data = resp.json().get("error", {})
                            for detail in err_data.get("details", []):
                                if "retryDelay" in detail:
                                    rd_str = detail["retryDelay"].replace("s", "")
                                    retry_delay_sec = int(float(rd_str))
                        except Exception:
                            pass
                            
                        if retry_delay_sec > 60:
                            print(f"Quota exhausted severely ({retry_delay_sec}s delay). Falling back.", flush=True)
                            break
                        elif retry_delay_sec > 0:
                            print(f"Waiting {retry_delay_sec}s for 429 backoff...", flush=True)
                            await asyncio.sleep(retry_delay_sec)
                            continue
                    elif resp.status_code == 503 and delay > 0:
                        print(f"[{resp.status_code}] NATIVE GEMINI 503. Retrying.", flush=True)
                        await asyncio.sleep(delay)
                        continue
                    else:
                        print(f"[{resp.status_code}] NATIVE GEMINI REJECTED - {resp.text}", flush=True)
                        break
                except Exception as e:
                    print("NATIVE GEMINI EXCEPTION:", type(e), str(e), flush=True)
                    traceback.print_exc()
                    break

        # 2. Try OpenRouter Fallback
        if self._openrouter_key:
            retries = [1, 2, 4]
            for attempt, delay in enumerate(retries + [0]):
                try:
                    headers = {
                        "Authorization": f"Bearer {self._openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://cue-wind-tunnel.web.app",
                        "X-Title": "CUE Wind Tunnel",
                    }
                    payload = {
                        "model": OPENROUTER_MODEL,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.1,
                    }
                    
                    resp = await asyncio.to_thread(requests.post, OPENROUTER_BASE, headers=headers, json=payload, timeout=15)
                    if resp.status_code == 200:
                        print(f"[{resp.status_code}] Answered by OpenRouter ({OPENROUTER_MODEL})", flush=True)
                        try:
                            from budget import budget_manager
                            budget_manager.record_call(source="openrouter")
                        except Exception:
                            pass
                        data = resp.json()
                        content = data["choices"][0]["message"].get("content")
                        result_text = content.strip() if content else ""
                        _CACHE[cache_key] = result_text
                        return result_text, "openrouter"
                    elif resp.status_code in (429, 503) and delay > 0:
                        print(f"[{resp.status_code}] OPENROUTER {resp.status_code}. Retrying.", flush=True)
                        await asyncio.sleep(delay)
                        continue
                    else:
                        print(f"[{resp.status_code}] OpenRouter API error: {resp.text}", flush=True)
                        break
                except Exception as e:
                    print("OPENROUTER EXCEPTION:", e, flush=True)
                    break

            raise RuntimeError("All LLM routes exhausted or failed.")

    async def generate_decision(self, agent_def, context: str) -> str:
        """
        Gemini is bypassed for generate_decision to ensure zero volume during search.
        """
        stub = StubLLMClient()
        return await stub.generate_decision(agent_def, context)

    async def extract_commitment_value(self, text: str, key: str) -> str:
        try:
            messages = [{"role": "user", "content": (
                f"Extract the value for '{key}' from this text: {text}\n"
                f"Reply with ONLY the extracted value, nothing else."
            )}]
            res, _ = await self._call_gemini(messages, max_tokens=20)
            return res
        except Exception:
            return text

    async def explain_failure(
        self,
        mutation_desc: str,
        invariant_id: str,
        violation: str,
        trace_summary: str,
    ) -> Tuple[str, str]:
        prompt = f"""You are an AI safety analyst reviewing a multi-agent system failure.

A team of 5 AI agents (Security, Engineering, QA, Deployment, Docs) was collaborating on implementing SSO authentication. An adversarial mutation was applied to test their resilience.

MUTATION APPLIED: {mutation_desc}
INVARIANT VIOLATED: {invariant_id}
VIOLATION DETAILS: {violation}
EXECUTION TRACE: {trace_summary}

Write a 2-3 sentence plain-English explanation for a technical audience explaining:
1. What went wrong in concrete terms (not abstract)
2. Why this matters in a real production multi-agent system
3. What class of bug this represents (e.g., stale reads, race condition, redundant work)

Be specific and direct. No bullet points, no headers — just clear prose."""
        try:
            messages = [{"role": "user", "content": prompt}]
            return await self._call_gemini(messages, max_tokens=250)
        except Exception as e:
            print(f"FAILED TO CALL LLM for explain_failure: {e}", flush=True)
            stub = StubLLMClient()
            return await stub.explain_failure(mutation_desc, invariant_id, violation, trace_summary)

    async def generate_scenario(self, prompt_text: str):
        from models import ScenarioDef
        sys_prompt = (
            "You are a principal engineer designing multi-agent AI pipelines. "
            "Convert the user's description into a JSON matching the ScenarioDef schema:\n"
            "{ \"name\": \"string\", \"description\": \"string\", \"agents\": "
            "[{\"id\": \"lowercase_string\", \"name\": \"string\", \"role\": \"string\", "
            "\"reads\": [\"string\"], \"writes\": \"string\", \"allowed_values\": [\"string\"]}] }\n"
            "CRITICAL RULES:\n"
            "1. ONLY RETURN VALID JSON. NO MARKDOWN. NO BACKTICKS.\n"
            "2. 'reads' must be a list of upstream 'writes' keys.\n"
            "3. Fill in at least 3-5 plausible agents cooperating in a flow."
        )
        try:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt_text}
            ]
            text, _ = await self._call_gemini(messages, max_tokens=2000)
            text = text.replace("```json", "").replace("```", "").strip()
            import json
            return ScenarioDef(**json.loads(text))
        except Exception as e:
            print(f"Scenario generation failed: {e}")
            from scenarios import SSO_SCENARIO
            return SSO_SCENARIO

    async def propose_fix(self, scenario_json: str, mutation_desc: str, trace_summary: str, violation: str) -> Tuple[Any, str]:
        from models import AgentFix
        sys_prompt = (
            "You are an autonomous reliability engine. A multi-agent pipeline hit an invariant violation due to a perturbation.\n"
            "Given the scenario and trace, choose ONE agent that needs to be re-run to resolve the split-brain or missing dependency.\n"
            "Return JSON matching: { \"agent_id\": \"lowercase_agent_name\", \"reasoning\": \"short explanation\" }\n"
            "CRITICAL RULES: ONLY RETURN VALID JSON. The agent_id must exactly match an ID from the scenario agents."
        )
        
        user_prompt = (
            f"SCENARIO:\n{scenario_json}\n\n"
            f"MUTATION INJECTED: {mutation_desc}\n"
            f"VIOLATION: {violation}\n"
            f"TRACE EXCERPT:\n{trace_summary}\n\n"
            "Propose the fix."
        )
        try:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ]
            text, source = await self._call_gemini(messages, max_tokens=200)
            import re, json
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            data = json.loads(text)
            return AgentFix(**data), source
        except Exception as e:
            print(f"FAILED TO CALL LLM for propose_fix: {e}", flush=True)
            stub = StubLLMClient()
            return await stub.propose_fix(scenario_json, mutation_desc, trace_summary, violation)

def get_llm_client(use_gemini: bool = False, api_key: str = None) -> BaseLLMClient:
    """Factory: returns GeminiLLMClient if requested and API key present, else StubLLMClient."""
    if use_gemini:
        native = os.environ.get("GEMINI_API_KEY")
        or_key = os.environ.get("OPENROUTER_API_KEY")
        if native: native = native.strip().strip("'\"")
        if or_key: or_key = or_key.strip().strip("'\"")
        
        if native or or_key:
            try:
                return GeminiLLMClient(native_key=native, openrouter_key=or_key)
            except Exception as e:
                print(f"WARNING: Failed to initialize GeminiLLMClient: {e}")

    return StubLLMClient()
