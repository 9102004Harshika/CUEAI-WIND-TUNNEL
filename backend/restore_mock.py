with open('llm_client.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('f"Live Gemini Reasoning: Simulated response for {target}."', 'f"Offline mode heuristic selected root cause: \'{target}\'."')

with open('llm_client.py', 'w', encoding='utf-8') as f:
    f.write(text)
