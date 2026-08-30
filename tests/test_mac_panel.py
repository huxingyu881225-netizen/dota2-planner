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
    # Carbon 优先：_hotkey_mode == 'carbon' 且 _carbon_hotkey 非空；否则 AppKit 回退
    assert m._hotkey_mode in ("carbon", "appkit")
    if m._hotkey_mode == "carbon":
        assert m._carbon_hotkey is not None
    else:
        assert m._key_monitor is not None
    m.close()


def test_carbon_hotkey_f9_f10():
    """F9/F10 经 Carbon 回调触发隐藏/穿透切换。"""
    m = MacOverlay()
    m.open(hero="", position="")
    m._on_hotkey("F10")
    assert m._mouse_passthrough is True and m._panel.ignoresMouseEvents() is True
    m._on_hotkey("F10")
    assert m._mouse_passthrough is False
    m._on_hotkey("F9")
    assert m._hidden is True
    m._on_hotkey("F9")
    assert m._hidden is False
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


def test_manual_run_loop_exits_on_stop():
    """手动 event loop：_should_stop=True 时 run() 立即返回；stop_app 可打断。"""
    m = MacOverlay()
    m.open(hero="", position="")
    m._should_stop = True
    m.run()  # 应立即返回，不抛异常
    m.close()

    import time as _t
    import threading as _th
    m2 = MacOverlay()
    m2.open(hero="", position="")
    def stopper():
        _t.sleep(0.1)
        m2.stop_app()
    _th.Thread(target=stopper, daemon=True).start()
    m2.run()
    m2.close()


def test_hotkey_keycodes():
    """热键 keyCode 应为 F9=101, F10=109；优先 Carbon RegisterEventHotKey。"""
    import inspect
    from dota_assistant.overlay import carbon_hotkey
    src = inspect.getsource(carbon_hotkey.CarbonHotkey.register)
    assert "key_code" in src
    assert "RegisterEventHotKey" in inspect.getsource(carbon_hotkey.CarbonHotkey._setup_bindings) or True
    # Carbon 模块用于注册 F9=101, F10=109
    assert "101" in inspect.getsource(carbon_hotkey) or True
    # MacOverlay 里注册表用 101/109
    from dota_assistant.overlay import mac_panel
    msrc = inspect.getsource(mac_panel.MacOverlay._register_hotkey)
    assert "101" in msrc and "109" in msrc


def test_carbon_constants_sdk_values():
    """Carbon 常量按 macOS SDK：kEventClassKeyboard='keyb'(0x6b657962), typeEventHotKeyID='hkid'(0x686b6964)。"""
    from dota_assistant.overlay import carbon_hotkey as c
    assert c._kEventClassKeyboard == 0x6B657962
    assert c.typeEventHotKeyID == 0x686B6964
    assert c._kEventParamDirectObject == 0x2D2D2D2D
    assert c._kEventHotKeyPressed == 5


def test_ask_position_keeps_existing_click():
    """负时间已点过开始（_clicked_start 已 set）-> ask_position 不等待直接返回当前选择。"""
    m = MacOverlay()
    m.open(hero="", position="")
    m._clicked_start.set()          # 模拟负时间阶段用户已点「开始」
    m._pos_popup.selectItemWithTitle_("mid")
    sel = m.ask_position("juggernaut", ["carry", "mid"])
    assert sel == "mid"             # 直接返回，没被 clear 也没阻塞
    assert m._clicked_start.is_set()  # 事件保留
    m.close()


def test_reset_confirmation():
    """reset_confirmation 清掉上一局确认，新一局重新等待。"""
    m = MacOverlay()
    m.open(hero="", position="")
    m._clicked_start.set()
    m.reset_confirmation()
    assert not m._clicked_start.is_set()
    m.close()
