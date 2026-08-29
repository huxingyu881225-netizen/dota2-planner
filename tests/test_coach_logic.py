"""测试 Coach 新逻辑：GSI 英雄感知 -> 位置仅从库中有数据的位置选择 -> 仅当(英雄,位置)有advice才提。"""

import types

from dota_assistant.overlay.coach import Coach, SessionClock
from dota_assistant.overlay.gsi import GsiState


class FakeRepo:
    """模拟 advice 库。"""
    def __init__(self, data):
        # data: {(hero, position): {minute: [advice rows...]}} 简单起见用 list
        self.data = data or {}

    def advice_positions_for_hero(self, hero):
        return sorted({pos for (h, pos) in self.data if h == hero})

    def lookup_advice_at(self, hero, position, minute):
        rows = self.data.get((hero, position), [])
        return [r for r in rows if r["t_start_min"] <= minute < r["t_end_min"]]


class Rec:
    def __init__(self):
        self.shown = []

    def show(self, minute, text):
        self.shown.append((minute, text))


def make_clock():
    return SessionClock(start_minute=0.0)


def test_gsi_hero_detection():
    """英雄来自 GSI，位置从库里该英雄的位置自动选。"""
    gsi = GsiState()
    gsi.update({"map": {"game_time": 90, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
                "hero": {"info": {"name": "npc_dota_hero_juggernaut"}}, "player": {"team": 2}})
    repo = FakeRepo({("juggernaut", "carry"): [{"t_start_min": 0, "t_end_min": 5, "advice": "对线压制",
                                                 "t_start_min": 0.0, "t_end_min": 5.0}]})
    # 注意 FakeRepo.lookup 内部用 dict key，这里 row 需带 t_start_min/t_end_min
    rec = Rec()
    # 直接验证 Coach 的 _hero 与 _resolve_position
    c = Coach(repo, rec)
    c.gsi = gsi
    assert c._hero(None) == "juggernaut"
    assert c._resolve_position("juggernaut", None) == "carry"


def test_position_only_from_existing():
    """库里该英雄没有对应位置的 advice -> 位置解析为 None（不提）。"""
    gsi = GsiState()
    gsi.update({"map": {"game_time": 60, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
                "hero": {"info": {"name": "npc_dota_hero_pudge"}}, "player": {"team": 2}})
    repo = FakeRepo({})  # 空库
    c = Coach(repo, Rec())
    c.gsi = gsi
    assert c._hero(None) == "pudge"
    assert c._resolve_position("pudge", None) is None  # 无位置 -> 不提


def test_requested_position_not_in_db():
    """指定了位置但库里该英雄无此位置的 advice -> 解析为 None。"""
    repo = FakeRepo({("juggernaut", "carry"): [{"t_start_min": 0, "t_end_min": 5, "advice": "x"}]})
    c = Coach(repo, Rec())
    assert c._resolve_position("juggernaut", "mid") is None          # mid 不在库里
    assert c._resolve_position("juggernaut", "carry") == "carry"     # carry 在库里


def test_multiple_positions_ask_display():
    """多个位置时交给 display.ask_position。"""
    repo = FakeRepo({
        ("juggernaut", "carry"): [],
        ("juggernaut", "mid"): [],
    })
    class AskDisplay(Rec):
        def ask_position(self, hero, options):
            return "mid"
    c = Coach(repo, AskDisplay())
    assert c._resolve_position("juggernaut", None) == "mid"
