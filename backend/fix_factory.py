import os

with open('llm_client.py', 'r', encoding='utf-8') as f:
    text = f.read()

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
            try:
                return GeminiLLMClient(native_key=native, openrouter_key=or_key)
            except Exception as e:
                print(f"WARNING: Failed to initialize GeminiLLMClient: {e}")

    return StubLLMClient()"""

text = text.replace(get_old, get_new)

with open('llm_client.py', 'w', encoding='utf-8') as f:
    f.write(text)
