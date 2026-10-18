import sys

with open('api.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacement = """    return {
        "status": "ok",
        "result": result.model_dump(),
        "trace_serialized": serialize_trace(trace),
        "gemini_powered": USE_GEMINI and "Offline mode heuristic" not in fix.reasoning
    }"""

text = text.replace("""    return {
        "status": "ok",
        "result": result.model_dump(),
        "trace_serialized": serialize_trace(trace),
    }""", replacement)

with open('api.py', 'w', encoding='utf-8') as f:
    f.write(text)
