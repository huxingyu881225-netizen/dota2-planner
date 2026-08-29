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
    assert "juggernaut" in p and "carry" in p and "核心策略" in p


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
    """默认 max_tokens=500，且 DOTA_LLM_REASONING_EFFORT 会进入请求体。"""
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
    assert captured["body"]["max_tokens"] == 500
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
