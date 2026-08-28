import os
from unittest import mock

from dota_assistant.core.models import Deviation
from dota_assistant.llm.judger import enrich_with_llm


def make_devs():
    return [
        Deviation(t_min=1.0, field="cs", actual=5, reference=10, direction="lower", outcome="bad", note="规则"),
        Deviation(t_min=2.0, field="gpm", actual=600, reference=500, direction="higher", outcome="good", note="规则"),
    ]


class FakeResp:
    def __init__(self, content):
        self._c = content
    def raise_for_status(self):
        pass
    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def test_no_key_keeps_rule(monkeypatch):
    monkeypatch.delenv("DOTA_LLM_API_KEY", raising=False)
    devs = make_devs()
    ok = enrich_with_llm(devs, "juggernaut", "carry", "loss")
    assert ok is False
    assert devs[0].outcome == "bad" and devs[0].note == "规则"


def test_llm_overrides(monkeypatch):
    monkeypatch.setenv("DOTA_LLM_API_KEY", "test-key")
    content = (
        '[{"index": 0, "outcome": "neutral", "note": "前期对线补刀略低但英雄组合因素为主。"},'
        ' {"index": 1, "outcome": "good", "note": "经济节奏好，压制对手。"}]'
    )
    def fake_post(*a, **k):
        return FakeResp(content)
    monkeypatch.setattr("dota_assistant.llm.judger.requests.post", fake_post)
    devs = make_devs()
    ok = enrich_with_llm(devs, "juggernaut", "carry", "loss")
    assert ok is True
    assert devs[0].outcome == "neutral" and "英雄组合" in devs[0].note
    assert devs[1].outcome == "good"


def test_llm_fenced_json(monkeypatch):
    monkeypatch.setenv("DOTA_LLM_API_KEY", "test-key")
    content = "```json\n[{\"index\": 0, \"outcome\": \"bad\", \"note\": \"补刀过低浪费时间\"}]\n```"
    def fake_post(*a, **k):
        return FakeResp(content)
    monkeypatch.setattr("dota_assistant.llm.judger.requests.post", fake_post)
    devs = make_devs()
    ok = enrich_with_llm(devs, "juggernaut", "carry", None)
    assert ok is True and devs[0].outcome == "bad"


def test_llm_failure_keeps_rule(monkeypatch):
    monkeypatch.setenv("DOTA_LLM_API_KEY", "test-key")
    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr("dota_assistant.llm.judger.requests.post", boom)
    devs = make_devs()
    ok = enrich_with_llm(devs, "juggernaut", "carry", None)
    assert ok is False
    assert devs[0].outcome == "bad" and devs[1].outcome == "good"
