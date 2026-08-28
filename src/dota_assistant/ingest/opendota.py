"""OpenDota data source.

Fetches /matches/{id} and /matches/{id}/timeline. Free tier, no API key needed
for public matches. Respects a basic rate limit.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

from dota_assistant.ingest.source import Source, match_hero_in_player

BASE = "https://api.opendota.com/api"


class OpenDotaSource(Source):
    name = "opendota"

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 30.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{BASE}{path}"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        time.sleep(0.3)  # gentle rate limit
        return resp.json()

    def fetch(self, match_id: str, hero: str, position: str, minute_n: int, interval_m: int):
        match = self._get(f"/matches/{match_id}")
        timeline = self._get(f"/matches/{match_id}/timeline")
        # select the desired hero's player
        players = match.get("players", [])
        target = next((p for p in players if match_hero_in_player(p, hero)), None)
        return {"match": match, "players": players, "timeline": timeline, "target": target}
