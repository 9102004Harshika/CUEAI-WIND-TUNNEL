import requests
import json

URL_MUTATE = "http://localhost:8000/api/mutate"
URL_FIX = "http://localhost:8000/api/fix"

payload = {
    "type": "duplicate",
    "target_agent": "qa",
    "target_key": ""
}

res = requests.post(URL_MUTATE, json=payload)
data = res.json()

if not data.get("all_passed"):
    violations = [r for r in data["invariant_results"] if not r["passed"]]
    failure = violations[0]
    print(f"FAILED (as expected): {failure['invariant_id']} -> {failure['reason']}")
    
    fix_payload = {
        "mutation": data["mutation"],
        "violation": failure['reason'],
        "invariant_id": failure['invariant_id'],
        "trace_summary": json.dumps(data["trace"][-5:])
    }
    
    print("\n--- TRIGGERING AUTONOMOUS FIX LOOP ---\n")
    fix_res = requests.post(URL_FIX, json=fix_payload)
    if fix_res.status_code == 200:
        result = fix_res.json()["result"]
        print(f"PROPOSED FIX AGENT: {result['fix']['agent_id']}")
        print(f"RE-EXECUTION PASSED (ALL): {result['success']}")
        for r in result['invariant_results']:
            print(f"  - {r['invariant_id']}: {'PASS' if r['passed'] else 'FAIL -> ' + str(r['reason'])}")
        
        dd_passed = next(r['passed'] for r in result['invariant_results'] if r['invariant_id'] == 'no_downstream_disagreement')
        if dd_passed:
            print("\n✨ System SUCCESSFULLY self-healed the downstream disagreement!")
        else:
            print("\n❌ Failed to heal downstream disagreement.")
    else:
        print("API ERROR:", fix_res.text)
else:
    print("NO FAILURE DETECTED!")
