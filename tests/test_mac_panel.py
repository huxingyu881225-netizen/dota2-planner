"""macOS 浮窗基础测试：ButtonTarget 可触发、面板可构建（无 GUI 时自动跳过）。"""
import pytest

AppKit = pytest.importorskip("AppKit")

from dota_assistant.overlay.mac_panel import MacOverlay, _ButtonTarget


def test_button_target_selector_fires():
    fired = []
    t = _ButtonTarget.alloc().initWithCallback_(lambda: fired.append(1))
    assert fired == []
    getattr(t, "startCoach_")(None)   # 触发按钮 action
    assert fired == [1]


def test_overlay_build_and_display():
    m = MacOverlay()
    m.open(hero="axe", position="offlane_support")
    assert m._panel is not None
    assert m._hero_label is not None
    assert m._pos_popup is not None
    assert m._advice_label is not None
    assert m.selected_position() == "offlane_support"
    m.show(1.5, "测试建议")
    m.set_hero_from_gsi("juggernaut")
    m.close()
