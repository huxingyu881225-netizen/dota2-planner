"""TTS 语音播报测试（mock 子进程，不真发声）。"""
from unittest import mock

import pytest

from dota_assistant.overlay.tts import TtsSpeaker, _say_path
from dota_assistant.overlay.coach import Coach
from dota_assistant.overlay.gsi import GsiState


class FakeProc:
    def __init__(self, name="p"):
        self.name = name
        self.killed = False
    def kill(self):
        self.killed = True


def test_say_path_macos_if_exists(monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys, "platform", "darwin")
    with mock.patch("dota_assistant.overlay.tts.shutil.which", return_value="/usr/bin/say"):
        p = _say_path()
    assert p == "/usr/bin/say"


def test_non_mac_noop(monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys, "platform", "linux")
    sp = TtsSpeaker()
    assert sp.available is False
    assert sp.speak("测试") is False


def test_speak_starts_process_and_async(monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys, "platform", "darwin")
    proc = FakeProc()
    with mock.patch("dota_assistant.overlay.tts.subprocess.Popen", return_value=proc) as pop:
        sp = TtsSpeaker()
        assert sp.available is True
        ok = sp.speak("开局对线压制")
        assert ok is True
        pop.assert_called_once()
        # 不阻塞调用方
        sp.speak("下一条建议")
        assert pop.call_count == 2
    sp.stop()


def test_new_speak_kills_previous(monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys, "platform", "darwin")
    proc1, proc2 = FakeProc("p1"), FakeProc("p2")
    with mock.patch("dota_assistant.overlay.tts.subprocess.Popen",
                    side_effect=[proc1, proc2]) as pop:
        sp = TtsSpeaker()
        sp.speak("第一条")
        assert sp._proc is proc1
        sp.speak("第二条")
        assert proc1.killed is True          # 上一条被打断
        assert sp._proc is proc2
    sp.stop()


def test_coach_speaks_only_on_new_advice():
    """Coach：只在命中新 advice 时调用 tts.speak；等待/无英雄/库中无数据提示不播。"""
    gsi = GsiState()
    gsi.update({"map": {"clock_time": 60, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", "matchid": "1"},
                "hero": {"info": {"name": "npc_dota_hero_juggernaut"}}, "player": {"team": 2}})

    class FakeRepo:
        def advice_positions_for_hero(self, hero):
            return ["carry"]
        def lookup_advice_at(self, hero, position, minute):
            return [{"t_start_min": 0, "t_end_min": 5, "advice": "对线压制"}]

    class Rec:
        def __init__(self):
            self.shown = []
        def show(self, m, t):
            self.shown.append((m, t))
        def set_hero_from_gsi(self, h):
            pass

    class FakeTTS:
        def __init__(self):
            self.said = []
        def speak(self, text):
            self.said.append(text)

    tts = FakeTTS()
    # 直接验证 speak 被调用逻辑：手动跑一轮 run 需要无限循环，改为单步验证：
    # 用自定义 clock 只返回一次 1.0 然后永远 None（避免退出），并在线程里跑
    import threading, time
    from dota_assistant.overlay.coach import GsiGameClock

    class OnceClock(GsiGameClock):
        def __init__(self, st):
            super().__init__(st)
            self.calls = 0
        def minute(self):
            self.calls += 1
            if self.calls == 1:
                return 1.0
            return None

    c = Coach(FakeRepo(), Rec(), clock=OnceClock(gsi), gsi_state=gsi, tts=tts)
    t = threading.Thread(target=lambda: c.run(minute_n=5, interval_m=1), daemon=True)
    t.start()
    time.sleep(0.3)
    assert tts.said == ["对线压制"], tts.said   # 只播了一次 advice
    # 线程退出（clock 返回 None 后无限等，daemon 无所谓）
