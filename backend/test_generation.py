import requests
import time
import json

URL = "http://localhost:8080/api/scenario/generate"

prompts = [
    "A self-driving car sensor fusion system. Agents: Lidar, Camera, Radar, FusionNode, BrakeController. Lidar, Camera, Radar write raw data. FusionNode reads them and writes a fused_obstacle map. BrakeController reads fused_obstacle map to decide whether to brake.",
    "A hedge fund algorithmic trading desk. Agents: MarketDataFetcher, SentimentAnalyzer, QuantModel, RiskOfficer, OrderExecution. They chain together sequentially to trade.",
    "A content publishing platform. Agents: Writer, SEOOptimizer, Editor, LegalReview, Publisher. The Writer writes the draft, SEO and Editor review it, Legal approves it, Publisher pushes it."
]

def test():
    for p in prompts:
        print(f"\nPrompt: {p[:50]}...")
        try:
            r = requests.post(URL, json={"prompt": p}, timeout=30)
            if r.status_code == 200:
                data = r.json()
                print("SUCCESS!")
                print(f"Scenario Name: {data.get('scenario', {}).get('name')}")
                agents = data.get('scenario', {}).get('agents', [])
                print(f"Generated {len(agents)} agents.")
                for a in agents:
                    print(f"  - {a.get('id')} ({a.get('name')}): Writes ({a.get('writes')}) Reads ({a.get('reads')})")
            else:
                print(f"FAILED: HTTP {r.status_code}")
                print(r.text)
        except Exception as e:
            print(f"REQUEST FAILED: {e}")
        time.sleep(1)

if __name__ == "__main__":
    test()
