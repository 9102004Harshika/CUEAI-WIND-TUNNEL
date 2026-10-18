import asyncio
import os
import aiohttp
import json

async def run():
    from dotenv import load_dotenv
    load_dotenv('.env')
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={os.environ.get('GEMINI_API_KEY').strip()}"
    payload = {
        "contents": [{"parts": [{"text": "Return exactly the JSON object: {'agent_id': 'test', 'reasoning': 'test'}"}]}],
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.1}
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            print("Status:", resp.status)
            print("Response:", await resp.text())

if __name__ == "__main__":
    asyncio.run(run())
