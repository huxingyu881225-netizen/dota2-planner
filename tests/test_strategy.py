import os
import pytest
from unittest import mock

from dota_assistant.llm.strategy import generate_strategy_batch, strategy_prompt

WIN = {"t_sec": 150, "t_min": 2.5, "window_interval": 30, "cs": 22, "gpm": 520,
       "networth": 3000, "gold": 400, "xp": 1500, "dn": 3, "window_gain": 180,
       "kills_total": 1, "deaths": 0, "assists": 1, "kills_in_window": 0,
       "obs_bought": 0, "sen_bought": 0}


def test_strategy_prompt_contains_hero_position():
    p = strategy_prompt("juggernaut", "carry", WIN)
    assert "juggernaut" in p and "carry" in p and "advice:" in p


def test_template_fallback_without_key(monkeypatch):
    monkeypatch.delenv("DOTA_LLM_API_KEY", raising=False)
    out = generate_strategy_batch([WIN, WIN], "juggernaut", "carry", api_key=None)
    assert len(out) == 2
    assert all(len(t) > 0 for t in out)


def test_mocked_llm_batch(monkeypatch):
    monkeypatch.setenv("DOTA_LLM_API_KEY", "test-key")

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": "游走中路支援，围绕大招节奏。", "role": "assistant"}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        assert "/chat/completions" in url
        assert headers["Authorization"] == "Bearer test-key"
        return FakeResp()

    monkeypatch.setattr("dota_assistant.llm.strategy.requests.post", fake_post)
    out = generate_strategy_batch([WIN, WIN], "juggernaut", "carry")
    assert out == ["游走中路支援，围绕大招节奏。", "游走中路支援，围绕大招节奏。"]


def test_llm_failure_falls_back_to_template(monkeypatch):
    monkeypatch.setenv("DOTA_LLM_API_KEY", "test-key")
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr("dota_assistant.llm.strategy.requests.post", boom)
    out = generate_strategy_batch([WIN], "juggernaut", "carry")
    assert len(out) == 1 and len(out[0]) > 0  # fallback template


def test_llm_max_tokens_and_reasoning(monkeypatch):
    """默认 max_tokens=1000，且 DOTA_LLM_REASONING_EFFORT 会进入请求体。"""
    monkeypatch.setenv("DOTA_LLM_API_KEY", "k")
    monkeypatch.setenv("DOTA_LLM_REASONING_EFFORT", "high")
    captured = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "稳发育"}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return R()

    monkeypatch.setattr("dota_assistant.llm.strategy.requests.post", fake_post)
    out = generate_strategy_batch([WIN], "juggernaut", "carry")
    assert out == ["稳发育"]
    assert captured["body"]["max_tokens"] == 1000
    assert captured["body"].get("reasoning_effort") == "high"


def test_llm_max_tokens_env(monkeypatch):
    """DOTA_LLM_MAX_TOKENS 可覆盖默认 500。"""
    monkeypatch.setenv("DOTA_LLM_API_KEY", "k")
    monkeypatch.setenv("DOTA_LLM_MAX_TOKENS", "300")
    captured = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "x"}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return R()

    monkeypatch.setattr("dota_assistant.llm.strategy.requests.post", fake_post)
    generate_strategy_batch([WIN], "juggernaut", "carry")
    assert captured["body"]["max_tokens"] == 300


def test_strategy_prompt_position_chinese(monkeypatch):
    """strategy_prompt 带位置中文映射，且包含 advice 结尾。"""
    from dota_assistant.llm.strategy import strategy_prompt, POSITION_CN
    p = strategy_prompt("axe", "offlane_support", WIN)
    assert "劣势路辅助/四号位" in p
    assert "位置:offlane_support(劣势路辅助/四号位)" in p
    assert p.strip().endswith("advice:")
    # 中文映射表包含全部5个位置
    assert POSITION_CN["carry"] == "一号位/优势路核心"
    assert POSITION_CN["safelane_support"] == "五号位/优势路辅助"


def test_system_prompt_has_structure_and_constraints():
    """SYSTEM_PROMPT 含两部分结构与关键约束，且严禁复述例子状态/数据。"""
    from dota_assistant.llm.strategy import SYSTEM_PROMPT
    assert "装备/补给/视野建议" in SYSTEM_PROMPT
    assert "战术指令" in SYSTEM_PROMPT
    assert "starting_items" in SYSTEM_PROMPT
    assert "offlane_support" in SYSTEM_PROMPT and "劣势路辅助/四号位" in SYSTEM_PROMPT
    assert "一到三句中文" in SYSTEM_PROMPT
    assert "必须至少包含一个具体动作" in SYSTEM_PROMPT
    # 禁止复述例子状态
    assert "严禁复述" in SYSTEM_PROMPT
    assert "本局9杀1死" in SYSTEM_PROMPT
    assert "只输出行动" in SYSTEM_PROMPT or "输出只留结论" in SYSTEM_PROMPT


def test_reasoning_effort_default_high(monkeypatch):
    """reasoning_effort 默认 high（未设环境变量也进 payload）。"""
    monkeypatch.setenv("DOTA_LLM_API_KEY", "k")
    monkeypatch.delenv("DOTA_LLM_REASONING_EFFORT", raising=False)
    captured = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "x"}}]}
    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return R()
    monkeypatch.setattr("dota_assistant.llm.strategy.requests.post", fake_post)
    from dota_assistant.llm.strategy import generate_strategy_batch
    generate_strategy_batch([WIN], "juggernaut", "carry")
    assert captured["body"].get("reasoning_effort") == "high"


def test_action_signal_strips_raw_numbers():
    """_action_signal 去掉原始战况数字，只留定性行动信号。"""
    from dota_assistant.llm.strategy import _action_signal
    sig = _action_signal({
        "t_sec": 150, "t_min": 2.5, "window_interval": 30,
        "cs": 22, "gpm": 520, "networth": 3000, "gold": 400,
        "xp": 1500, "dn": 3, "window_gain": 180,
        "kills_total": 9, "deaths": 1, "assists": 3,
        "kills_in_window": 1, "obs_bought": 2, "sen_bought": 1,
        "starting_items": ["tango", "magic stick"],
        "items_bought_so_far": ["tango", "magic stick", "boots"],
        "items_bought_in_window": ["boots"],
        "pos_x": 100.0, "pos_y": 200.0,
    })
    # 不应出现的原始状态字段
    for k in ("kills_total", "deaths", "assists", "cs", "gpm", "networth", "gold", "xp", "dn", "window_gain", "kills_in_window"):
        assert k not in sig, f"不应出现原始字段 {k}: {sig}"
    # 应保留的定性/行动信号
    assert sig.get("经济水平") == "中"          # gpm=520 -> 中
    assert sig.get("起始装") == ["tango", "magic stick"]
    assert sig.get("已有装备") == ["tango", "magic stick", "boots"]
    assert sig.get("本窗口新增") == ["boots"]
    assert sig.get("视野") == "有插眼动作"
    assert sig.get("地图位置") == [100, 200]
