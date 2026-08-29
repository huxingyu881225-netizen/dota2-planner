"""Coach loop (requirement 2).

每 M 秒查 DB 对应时间段的 advice 并显示（浮窗/终端）。

时钟来源（GameClockProvider）：
    1. GSI —— 接 Dota 2 Game State Integration，用 map.game_time 从游戏开始自动计时（推荐）。
    2. 回退 —— 会话计时器（从程序启动计，未接 GSI 时用）。
"""
from __future__ import annotations

import time
from typing import Optional

from dota_assistant.overlay.gsi import GsiState


class GameClock:
    """基础时钟接口：minute() 返回当前游戏分钟；未开始/未知返回 None。"""

    def minute(self) -> Optional[float]:
        raise NotImplementedError


class SessionClock(GameClock):
    """回退：从程序启动（或给定起点）计时。"""

    def __init__(self, start_minute: float = 0.0):
        self._start = time.monotonic() - start_minute * 60.0

    def minute(self) -> Optional[float]:
        return (time.monotonic() - self._start) / 60.0


class GsiGameClock(GameClock):
    """GSI 时钟：从游戏开始时（game_time 从 0 计）自动计时。

    未进入对局（GAME_IN_PROGRESS）或数据失效时 minute() 返回 None，
    coach 等待游戏真正开始。
    """

    def __init__(self, state: GsiState):
        self.state = state

    def minute(self) -> Optional[float]:
        if not self.state.fresh:
            return None
        return self.state.game_time / 60.0


class Coach:
    def __init__(self, repo, display, clock: Optional[GameClock] = None, gsi_state: Optional[GsiState] = None):
        self.repo = repo
        self.display = display
        if clock is not None:
            self.clock = clock
        elif gsi_state is not None:
            self.clock = GsiGameClock(gsi_state)
        else:
            self.clock = SessionClock()
        self._last_note = None

    def _hero_from_gsi(self) -> Optional[str]:
        """从 GSI 自动识别英雄 NPC 名 -> 纯名（如 npc_dota_hero_juggernaut -> juggernaut）。"""
        gsi = getattr(self, "_gsi_state", None)
        if gsi is None:
            return None
        name = gsi.hero_name
        if not name:
            return None
        return name.replace("npc_dota_hero_", "")

    def run(self, hero: str, position: str, minute_n: int, interval_m: int):
        if minute_n <= 0 or interval_m <= 0:
            raise ValueError("minute_n 和 interval_m 必须为正数")
        last_shown: dict[str, str] = {}
        waiting = False
        while True:
            m = self.clock.minute()
            if m is None:
                if not waiting:
                    self.display.show(0.0, "(等待 Dota2 游戏开始… 请先开局)")
                    waiting = True
                time.sleep(min(interval_m, 5))
                continue
            waiting = False
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
