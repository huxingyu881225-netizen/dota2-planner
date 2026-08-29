"""Coach loop (requirement 2).

每 M 秒查 DB 对应时间段的 advice 并显示（浮窗/终端）。

核心逻辑：
- 英雄名：GSI 实时感知（hero.info.name），同步到浮窗（去重）。
- 位置：用户指定、或从库里该英雄已有 advice 的位置中选择；库里没有就直接提示。
- 查询条件：只有当 (英雄, 位置) 在 advice 表里有数据时，才按游戏时间提建议。
- 多局重置：检测到新 match（matchid/session 变化）时重置英雄/位置设置。

时钟来源：
    1. GSI —— coach_time(优先 clock_time，回退 game_time)从游戏开始自动计时；coach_time<0 时返回 None。
    2. 回退 —— 会话计时器（未接 GSI 时用）。
"""
from __future__ import annotations

import time
from typing import Optional

from dota_assistant.overlay.gsi import GsiState


class GameClock:
    def minute(self) -> Optional[float]:
        raise NotImplementedError


class SessionClock(GameClock):
    """回退：从程序启动（或给定起点）计时。"""

    def __init__(self, start_minute: float = 0.0):
        self._start = time.monotonic() - start_minute * 60.0

    def minute(self) -> Optional[float]:
        return (time.monotonic() - self._start) / 60.0


class GsiGameClock(GameClock):
    """GSI 时钟：coach_time(优先 clock_time)从游戏开始自动计时。

    - 必须 fresh 且 in_game（GAME_IN_PROGRESS）
    - coach_time < 0（选人/策略阶段倒计时）时返回 None，避免提前吐 advice
    """

    def __init__(self, state: GsiState):
        self.state = state

    def minute(self) -> Optional[float]:
        if not self.state.fresh:
            return None
        if not self.state.in_game:
            return None
        ct = self.state.coach_time
        if ct < 0:
            return None
        return ct / 60.0


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
        self._last_match_id: Optional[str] = None
        self._pos_hero: Optional[str] = None
        self._resolved_pos: Optional[str] = None

    # ---- 英雄：GSI 感知优先 ----
    def _hero(self, fallback: Optional[str]) -> Optional[str]:
        if self.gsi is not None:
            n = self.gsi.hero_name.replace("npc_dota_hero_", "").strip()
            if n:
                return n
        return fallback

    def _match_changed(self) -> bool:
        """检测是否进入新一局（matchid 变化）。无 GSI 时始终 False。"""
        if self.gsi is None:
            return False
        mid = self.gsi.match_id or self.gsi.session_id
        if not mid:
            return False
        changed = (self._last_match_id is not None and mid != self._last_match_id)
        self._last_match_id = mid
        return changed

    # ---- 位置解析 ----
    def _resolve_position(self, hero: str, requested: Optional[str],
                          force_confirm: bool = False) -> Optional[str]:
        """解析位置：库里该英雄存在 advice 的位置。

        - requested 指定且库里有 -> 用它
        - 库里该英雄只有一个位置，且非强制确认 -> 自动用
        - 多个位置，或 force_confirm（GUI 恒需用户确认）-> display.ask_position
        - 库里没有 -> None
        """
        options = self.repo.advice_positions_for_hero(hero)
        if requested:
            return requested if requested in options else None
        if not options:
            return None
        if len(options) == 1 and not force_confirm:
            return options[0]
        asker = getattr(self.display, "ask_position", None)
        if asker is not None:
            chosen = asker(hero, options)
            return chosen if chosen in options else None
        return options[0]

    def run(self, hero: Optional[str] = None, position: Optional[str] = None,
            minute_n: int = 10, interval_m: int = 30,
            force_position_confirm: bool = False):
        if minute_n <= 0 or interval_m <= 0:
            raise ValueError("minute_n 和 interval_m 必须为正数")
        last_shown: dict[str, str] = {}
        last_hint: Optional[str] = None

        # 记录用户显式指定的位置（多局重置后回到这个默认）
        explicit_position = position

        while True:
            m = self.clock.minute()
            if m is None:
                last_hint = self._hint(last_hint, "等待 Dota2 游戏开始… 请先开局（GSI 计时中）")
                time.sleep(min(interval_m, 5))
                continue

            # 多局切换：重置英雄/位置，回到初始状态，重新让用户确认
            if self._match_changed():
                self._resolved_pos = None
                self._pos_hero = None
                last_hint = None

            # 当前英雄（GSI 实时）
            cur_hero = self._hero(hero)
            if not cur_hero:
                last_hint = self._hint(last_hint, "未感知到英雄（GSI 未上报），暂不提建议")
                time.sleep(min(interval_m, 5))
                continue

            # 只要识别到英雄就同步到浮窗英雄标签（去重）
            sync = getattr(self.display, "set_hero_from_gsi", None)
            if sync is not None:
                sync(cur_hero)

            # 位置：英雄变化或新一局时（重新）解析
            if self._resolved_pos is None or self._pos_hero != cur_hero:
                self._resolved_pos = self._resolve_position(
                    cur_hero, explicit_position, force_confirm=force_position_confirm)
                self._pos_hero = cur_hero

            if self._resolved_pos is None:
                last_hint = self._hint(last_hint,
                                       f"库中没有 {cur_hero} 的建议数据（或该位置无建议），暂不提 advice",
                                       force=True)
                time.sleep(min(interval_m, 5))
                continue

            # 库中存在 (hero, position) -> 按游戏时间提 advice
            if m > minute_n:
                break
            hits = self.repo.lookup_advice_at(cur_hero, self._resolved_pos, m)
            if hits:
                txt = hits[0]["advice"]
                key = m // interval_m
                if last_shown.get(str(key)) != txt:
                    self.display.show(m, f"【{hits[0]['t_start_min']}-{hits[0]['t_end_min']}min】{txt}")
                    last_shown[str(key)] = txt
            else:
                self.display.show(m, f"（{cur_hero}/{self._resolved_pos} 该时间段暂无建议窗口）")
            time.sleep(min(interval_m, 5))

    def _hint(self, last_hint, text, force=False):
        if force or last_hint != text:
            self.display.show(0.0, text)
            return text
        return last_hint
