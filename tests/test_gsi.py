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
