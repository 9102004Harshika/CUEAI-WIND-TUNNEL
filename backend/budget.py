"""
CUE Wind Tunnel — Persistent Daily LLM Budget Tracker
Ensures daily call budgets persist across server restarts.
No secrets are stored here.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any

BUDGET_FILE = os.path.join(os.path.dirname(__file__), "daily_budget.json")
DEFAULT_DAILY_LIMIT = int(os.environ.get("CUE_DAILY_LLM_LIMIT", "250"))

class BudgetManager:
    def __init__(self, filepath: str = BUDGET_FILE, daily_limit: int = DEFAULT_DAILY_LIMIT):
        self.filepath = filepath
        self.daily_limit = daily_limit
        self._load()

    def _get_today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self):
        today = self._get_today_str()
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") == today:
                        self.used = data.get("used", 0)
                        self.calls = data.get("calls", [])
                        return
            except Exception:
                pass
        # Reset for new day or missing file
        self.used = 0
        self.calls = []
        self._save()

    def _save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump({
                    "date": self._get_today_str(),
                    "daily_limit": self.daily_limit,
                    "used": self.used,
                    "remaining": max(0, self.daily_limit - self.used),
                    "last_updated": time.time(),
                }, f, indent=2)
        except Exception:
            pass

    def can_call(self) -> bool:
        self._load()
        return self.used < self.daily_limit

    def record_call(self, source: str = "gemini_live"):
        self._load()
        self.used += 1
        self._save()

    def get_status(self) -> Dict[str, Any]:
        self._load()
        return {
            "date": self._get_today_str(),
            "daily_limit": self.daily_limit,
            "used_today": self.used,
            "remaining": max(0, self.daily_limit - self.used),
            "exhausted": self.used >= self.daily_limit,
        }

budget_manager = BudgetManager()
