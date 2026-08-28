"""Coach loop (requirement 2).

Every M seconds, look up advice for (hero, position) at the current game minute
and show it on the overlay (or terminal). Runs until the game minute reaches N.
"""
from __future__ import annotations

import time
from typing import Optional

from dota_assistant.db.database import connect, init_schema
from dota_assistant.db.repo import Repo


class GameClock:
    """Provides the current in-game minute.

    MVP: a session timer that starts at 0 and counts up in real seconds.
    Future: read Dota GSI `map.game_time` for true alignment.
    """

    def __init__(self, start_minute: float = 0.0):
        self._start = time.monotonic() - start_minute * 60.0

    def minute(self) -> float:
        return (time.monotonic() - self._start) / 60.0


class Coach:
    def __init__(self, repo: Repo, display, clock: Optional[GameClock] = None):
        self.repo = repo
        self.display = display
        self.clock = clock or GameClock()

    def run(self, hero: str, position: str, minute_n: int, interval_m: int):
        if minute_n <= 0 or interval_m <= 0:
            raise ValueError("minute_n 和 interval_m 必须为正数")
        last_shown: dict[str, str] = {}
        while True:
            m = self.clock.minute()
            if m > minute_n:
                break
            hits = self.repo.lookup_advice_at(hero, position, m)
            if hits:
                txt = hits[0]["advice"]
                key = m // interval_m
                if last_shown.get(str(key)) != txt:
                    self.display.show(m, f"【{hits[0]['t_start_min']}-{hits[0]['t_end_min']}min】{txt}")
                    last_shown[str(key)] = txt
            else:
                self.display.show(m, "(暂无该时间段的参考建议，请先编辑或灌入数据)")
            time.sleep(min(interval_m, 5))
