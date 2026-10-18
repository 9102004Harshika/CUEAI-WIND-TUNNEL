import os

with open('llm_client.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('async with aiohttp.ClientSession() as session:', 
'''print(f"NATIVE KEY: {bool(self._native_key)} | OR KEY: {bool(self._openrouter_key)}", flush=True)
        async with aiohttp.ClientSession() as session:''')

text = text.replace('print("NATIVE GEMINI EXCEPTION:", e)', 'print("NATIVE GEMINI EXCEPTION:", e, flush=True)')

# we can use replace carefully
text = text.replace('print(f"NATIVE GEMINI REJECTED: HTTP {resp.status} - {await resp.text()}")', 
'print(f"NATIVE GEMINI REJECTED: HTTP {resp.status} - {await resp.text()}", flush=True)')

text = text.replace('print("OpenRouter failed:', 'print("OpenRouter failed:', 1)

with open('llm_client.py', 'w', encoding='utf-8') as f:
    f.write(text)
