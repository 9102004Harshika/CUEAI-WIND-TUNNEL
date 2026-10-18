import urllib.request
import json
payload = {
    'mutation': {'type': 'content_flip', 'target_agent': 'qa', 'params': {}},
    'mutation_desc': 'flip qa flag',
    'trace_summary': 'trace...',
    'violation': 'deployment\'s active \'deploy_action\' is based on a stale read of \'qa_approval\'',
    'invariant_id': 'no_downstream_disagreement'
}
req = urllib.request.Request('http://localhost:8000/api/fix', method='POST', headers={'Content-Type': 'application/json'}, data=json.dumps(payload).encode('utf-8'))
try:
    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode('utf-8'))
        print('gemini_powered = ' + str(data.get('gemini_powered')))
        print('Reasoning String: ' + data['result']['fix']['reasoning'])
except Exception as e:
    import traceback
    traceback.print_exc()
