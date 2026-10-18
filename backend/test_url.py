import urllib.request
import os, json
from dotenv import load_dotenv
load_dotenv('.env')

req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', method='POST')
req.add_header('Authorization', f"Bearer {os.environ.get('OPENROUTER_API_KEY')}")
req.add_header('Content-Type', 'application/json')
payload = {'model': 'mistralai/mistral-7b-instruct:free', 'messages': [{'role': 'user', 'content': 'test'}]}

try:
    with urllib.request.urlopen(req, data=json.dumps(payload).encode('utf-8')) as res:
        print('SUCCESS:', res.read().decode())
except Exception as e:
    import traceback
    traceback.print_exc()
