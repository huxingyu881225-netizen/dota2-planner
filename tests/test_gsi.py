"""测试 GSI 服务器：解析游戏时间/英雄，GSI 时钟自动计时，POST 更新状态。"""
import http.client
import json
import threading

import pytest

from dota_assistant.overlay.gsi import GsiState, GsiServer
from dota_assistant.overlay.coach import GsiGameClock


def make_gsi(game_time=120.0, state_str="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", hero="npc_dota_hero_juggernaut"):
    return {
        "map": {"game_time": game_time, "game_state": state_str, "name": "map"},
        "hero": {"info": {"name": hero}, "name": hero},
        "player": {"team": 2},
    }


def test_gsi_state_parse():
    st = GsiState()
    st.update(make_gsi(150.0))
    assert st.game_time == 150.0
    assert st.hero_name == "npc_dota_hero_juggernaut"
    assert st.in_game is True


def test_gsi_not_in_game():
    st = GsiState()
    st.update(make_gsi(0.0, state_str="DOTA_GAMERULES_STATE_HERO_SELECTION"))
    assert st.in_game is False


def test_gsi_clock_minutes():
    st = GsiState()
    st.update(make_gsi(180.0))  # 3 分钟
    clock = GsiGameClock(st)
    assert clock.minute() == 3.0


def test_gsi_server_receives_post():
    st = GsiState()
    port = 6011  # 平衡测试端口
    srv = GsiServer(host="127.0.0.1", port=port, state=st)
    assert srv.start() is True
    try:
        # POST GSI JSON
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        body = json.dumps(make_gsi(240.0, hero="npc_dota_hero_axe"))
        conn.request("POST", "/", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()
        # 稍等服务器处理
        import time
        for _ in range(50):
            if st.hero_name:
                break
            time.sleep(0.05)
        assert st.game_time == 240.0
        assert st.hero_name == "npc_dota_hero_axe"
        assert st.game_time / 60.0 == 4.0
    finally:
        srv.stop()


def test_gsi_clock_requires_in_game():
    """英雄选择阶段（非 GAME_IN_PROGRESS）即使 fresh 也不应吐时间。"""
    st = GsiState()
    # 英雄选择：game_time 可能是 0，fresh 且 in_game=False
    st.update({"map": {"game_time": 0.0, "game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"},
               "hero": {"info": {"name": "npc_dota_hero_pudge"}}, "player": {"team": 2}})
    clock = GsiGameClock(st)
    assert clock.minute() is None

    # 对局进行中：返回分钟
    st.update({"map": {"game_time": 120.0, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
               "hero": {"info": {"name": "npc_dota_hero_pudge"}}, "player": {"team": 2}})
    assert clock.minute() == 2.0


def test_clock_time_preferred():
    """GSI 时间优先用 map.clock_time，缺失时回退 game_time。"""
    st = GsiState()
    st.update({"map": {"clock_time": 90.0, "game_time": 60.0,
                       "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
               "hero": {"info": {"name": "npc_dota_hero_axe"}}, "player": {"team": 2}})
    assert st.game_time == 90.0  # clock_time 优先

    st2 = GsiState()
    st2.update({"map": {"game_time": 45.0,
                        "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
                "hero": {"info": {"name": "npc_dota_hero_axe"}}, "player": {"team": 2}})
    assert st2.game_time == 45.0  # 无 clock_time 回退 game_time
