import os

with open('llm_client.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update GeminiLLMClient __init__
init_old = """    def __init__(self, api_key: str):
        self._api_key = api_key"""
init_new = """    def __init__(self, native_key: str = None, openrouter_key: str = None):
        self._native_key = native_key
        self._openrouter_key = openrouter_key
        self._api_key = self._native_key or self._openrouter_key"""

text = text.replace(init_old, init_new)

# 2. Update _call_gemini
call_old = """    async def _call_gemini(self, messages: list, max_tokens: int = 150) -> str:
        \"\"\"Make an async call to Gemini via OpenRouter.\"\"\"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
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

        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENROUTER_BASE, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"OpenRouter API error {resp.status}: {error_text}")
                data = await resp.json()
                content = data["choices"][0]["message"].get("content")
                return content.strip() if content else \"\""""

call_new = """    async def _call_gemini(self, messages: list, max_tokens: int = 150) -> str:
        \"\"\"Make an async call with fallback: Native Gemini -> OpenRouter.\"\"\"
        
        async with aiohttp.ClientSession() as session:
            # 1. Try Native Google API First
            if self._native_key:
                try:
                    native_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={self._native_key}"
                    
                    sys_prompt = next((m['content'] for m in messages if m['role'] == 'system'), "")
                    user_prompt = next((m['content'] for m in messages if m['role'] == 'user'), "")
                    
                    native_payload = {
                        "contents": [{"parts": [{"text": user_prompt}]}],
                        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1}
                    }
                    if sys_prompt:
                        native_payload["systemInstruction"] = {"parts": [{"text": sys_prompt}]}
                        
                    async with session.post(native_url, json=native_payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
                            return parts[0].get("text", "").strip()
                        else:
                            print(f"NATIVE GEMINI REJECTED: HTTP {resp.status} - {await resp.text()}")
                except Exception as e:
                    print("NATIVE GEMINI EXCEPTION:", e)

            # 2. Try OpenRouter Fallback
            if self._openrouter_key:
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
                
                async with session.post(OPENROUTER_BASE, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["choices"][0]["message"].get("content")
                        return content.strip() if content else ""
                    else:
                        error_text = await resp.text()
                        raise RuntimeError(f"OpenRouter API error {resp.status}: {error_text}")
                        
            raise RuntimeError("All LLM routes exhausted or failed.")"""

text = text.replace(call_old, call_new)

# 3. Update get_llm_client factory
get_old = """def get_llm_client(use_gemini: bool = False, api_key: str = None) -> BaseLLMClient:
    \"\"\"Factory: returns GeminiLLMClient if requested and API key present, else StubLLMClient.\"\"\"
    if use_gemini:
        if not api_key:
            api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GEMINI_API_KEY")
            if api_key:
                api_key = api_key.strip("'\"")
        if api_key:
            try:
                return GeminiLLMClient(api_key=api_key)
            except Exception as e:
                print(f"WARNING: Failed to initialize GeminiLLMClient: {e}")

    return StubLLMClient()"""

get_new = """def get_llm_client(use_gemini: bool = False, api_key: str = None) -> BaseLLMClient:
    \"\"\"Factory: returns GeminiLLMClient if requested and API key present, else StubLLMClient.\"\"\"
    if use_gemini:
        native = os.environ.get("GEMINI_API_KEY")
        or_key = os.environ.get("OPENROUTER_API_KEY")
        if native: native = native.strip("'\"")
        if or_key: or_key = or_key.strip("'\"")
        
        if native or or_key:
            return GeminiLLMClient(native_key=native, openrouter_key=or_key)

    return StubLLMClient()"""

text = text.replace(get_old, get_new)

with open('llm_client.py', 'w', encoding='utf-8') as f:
    f.write(text)
