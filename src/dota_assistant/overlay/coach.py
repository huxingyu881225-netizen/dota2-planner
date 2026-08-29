"""Coach loop (requirement 2).

每 M 秒查 DB 对应时间段的 advice 并显示（浮窗/终端）。

核心逻辑（按需求）：
- 英雄名：优先用 GSI 实时感知的 `hero.info.name`（浮窗不再需要输入英雄）。
- 位置：若用户未指定，则从库里该英雄**已有 advice 的位置**中选择；库里没有就直接提示。
- 查询条件：只有当 (英雄, 位置) 在 advice 表里有数据时，才按游戏时间提建议；
  未感知到游戏运行（GSI 没信号/未开局）或 库中无该 英雄+位置 → 不提 advice，只显示提示。

时钟来源：
    1. GSI —— map.game_time 从游戏开始自动计时（推荐）。
    2. 回退 —— 会话计时器（未接 GSI 时用）。
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
    """GSI 时钟：从游戏开始时（game_time 从 0 计）自动计时。未进对局返回 None。"""

    def __init__(self, state: GsiState):
        self.state = state

    def minute(self) -> Optional[float]:
        # 必须同时满足：GSI 数据新鲜 + 对局进行中（避免英雄选择阶段就吐 0:00 advice）
        if not self.state.fresh:
            return None
        if not self.state.in_game:
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
        self.gsi = gsi_state

    # ---- 英雄：GSI 感知优先 ----
    def _hero(self, fallback: Optional[str]) -> Optional[str]:
        """当前英雄名：GSI 实时感知优先；GSI 没有则用 fallback（用户/参数提供）。"""
        if self.gsi is not None:
            n = self.gsi.hero_name.replace("npc_dota_hero_", "").strip()
            if n:
                return n
        return fallback

    # ---- 位置解析 ----
    def _resolve_position(self, hero: str, requested: Optional[str]) -> Optional[str]:
        """把位置解析为「库里该英雄存在 advice 的位置」。

        - requested 指定且库里有 -> 用它
        - requested 指定但库里没有 -> 返回 None（表示不提示）
        - 库里该英雄只有一个位置 -> 自动用
        - 多个 -> 交给 display.ask_position(hero, options) 让用户选；返回 None 表示无法确定
        """
        options = self.repo.advice_positions_for_hero(hero)
        if not options:
            return None
        if requested:
            return requested if requested in options else None
        if len(options) == 1:
            return options[0]
        # 多个候选位置 -> 让显示层选择
        chosen = None
        asker = getattr(self.display, "ask_position", None)
        if asker is not None:
            chosen = asker(hero, options)
        return chosen if chosen in options else None

    def run(self, hero: Optional[str] = None, position: Optional[str] = None,
            minute_n: int = 10, interval_m: int = 30):
        if minute_n <= 0 or interval_m <= 0:
            raise ValueError("minute_n 和 interval_m 必须为正数")
        last_shown: dict[str, str] = {}
        last_hint: Optional[str] = None
        resolved_pos: Optional[str] = position  # 缓存已解析的位置

        while True:
            m = self.clock.minute()
            if m is None:
                last_hint = self._hint(last_hint, "等待 Dota2 游戏开始… 请先开局（GSI 计时中）")
                time.sleep(min(interval_m, 5))
                continue

            # 当前英雄（GSI 实时）
            cur_hero = self._hero(hero)
            if not cur_hero:
                last_hint = self._hint(last_hint, "未感知到英雄（GSI 未上报），暂不提建议")
                time.sleep(min(interval_m, 5))
                continue
            # 把 GSI 感知的英雄显示到浮窗
            set_hero = getattr(self.display, "set_hero_from_gsi", None)
            if set_hero is not None:
                set_hero(cur_hero)

            # 若英雄尚未解析出位置，或 GSI 英雄与解析时不同，重新解析
            if resolved_pos is None or getattr(self, "_pos_hero", None) != cur_hero:
                resolved_pos = self._resolve_position(cur_hero, position)
                self._pos_hero = cur_hero

            if resolved_pos is None:
                last_hint = self._hint(last_hint,
                                       f"库中没有 {cur_hero} 的建议数据（或该位置无建议），暂不提 advice",
                                       force=True)
                time.sleep(min(interval_m, 5))
                continue

            # 库中存在 (hero, position) -> 按游戏时间提 advice
            if m > minute_n:
                break
            # 一旦开始出建议，浮窗切到鼠标穿透模式（不挡游戏操作）
            start_mode = getattr(self.display, "start_advice_mode", None)
            if not getattr(self, "_advice_started", False):
                self._advice_started = True
                if start_mode is not None:
                    start_mode()
            hits = self.repo.lookup_advice_at(cur_hero, resolved_pos, m)
            if hits:
                txt = hits[0]["advice"]
                key = m // interval_m
                if last_shown.get(str(key)) != txt:
                    self.display.show(m, f"【{hits[0]['t_start_min']}-{hits[0]['t_end_min']}min】{txt}")
                    last_shown[str(key)] = txt
            else:
                self.display.show(m, f"（{cur_hero}/{resolved_pos} 该时间段暂无建议窗口）")
            time.sleep(min(interval_m, 5))

    def _hint(self, last_hint, text, force=False):
        """显示提示（去重：相同提示只显示一次）。"""
        if force or last_hint != text:
            self.display.show(0.0, text)
            return text
        return last_hint
