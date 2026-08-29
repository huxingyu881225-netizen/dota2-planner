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


def test_mouse_passthrough_manual_toggle():
    """鼠标穿透不再由 start_advice_mode 自动开启，改用 F10(toggle_mouse_passthrough) 手动控制。"""
    m = MacOverlay()
    m.open(hero="axe", position="carry")
    assert m._panel.ignoresMouseEvents() is False
    m.start_advice_mode()
    assert m._panel.ignoresMouseEvents() is False  # item6: 不自动穿透
    assert m.toggle_mouse_passthrough() is True     # F10 开启穿透
    assert m._panel.ignoresMouseEvents() is True
    assert m.toggle_mouse_passthrough() is False    # F10 切回可点击
    assert m._panel.ignoresMouseEvents() is False
    m.close()


def test_sync_display_hero_dedup():
    m = MacOverlay()
    m.open(hero="", position="")
    m.set_hero_from_gsi("juggernaut")
    m.set_hero_from_gsi("juggernaut")
    m.set_hero_from_gsi("juggernaut")
    assert m._hero_label.stringValue() == "juggernaut"
    m.set_hero_from_gsi("axe")
    assert m._hero_label.stringValue() == "axe"
    m.close()


def test_toggle_visible():
    m = MacOverlay()
    m.open(hero="", position="")
    assert m._hidden is False
    m.toggle_visible()
    assert m._hidden is True and m._panel.isVisible() is False
    m.toggle_visible()
    assert m._hidden is False and m._panel.isVisible() is True
    m.close()


def test_register_hotkey():
    m = MacOverlay()
    m.open(hero="", position="")
    m._register_hotkey()
    assert m._key_monitor is not None
    m.close()


def test_overlay_position_env(monkeypatch):
    """DOTA_OVERLAY_X/Y 生效；未设置时默认右上角。"""
    import os
    monkeypatch.setenv("DOTA_OVERLAY_X", "100")
    monkeypatch.setenv("DOTA_OVERLAY_Y", "200")
    m = MacOverlay()
    m.open(hero="", position="")
    f = m._panel.frame()
    assert int(f.origin.x) == 100 and int(f.origin.y) == 200
    m.close()
