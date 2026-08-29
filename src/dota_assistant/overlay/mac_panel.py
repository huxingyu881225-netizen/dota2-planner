"""macOS floating overlay via NSPanel (pyobjc).

Reference: dota-ai-coach floating window. Always-on-top, non-activating,
borderless. 本面板支持：输入框（英雄/位置）+ 开始按钮 + 建议显示区，
用户可在浮窗上直接输入英雄名与位置来输出 advice。

若 pyobjc 不可用则抛错，由 CLI 降级到终端模式。
"""
from __future__ import annotations

import threading
from typing import Optional

try:
    import AppKit
    import objc
    _HAS_MAC = True
except Exception:  # pragma: no cover - non-mac or missing pyobjc
    _HAS_MAC = False


class MacOverlay:
    """可输入英雄/位置、可显示建议的 macOS 置顶浮窗。调用需在主线程（或 runloop）。"""

    POSITIONS = ["carry", "mid", "offline", "offlane_support", "safelane_support"]

    def __init__(self):
        if not _HAS_MAC:
            raise RuntimeError("pyobjc-framework-Cocoa not available; use terminal mode")
        self._panel = None
        self._hero_field = None
        self._pos_field = None
        self._advice_label = None
        self._running = False
        self._props_lock = threading.Lock()
        self._clicked_start = threading.Event()

    # -- 线程安全地读取用户在浮窗输入的内容 --
    def get_selection(self):
        """返回 (hero, position)；未填则返回 (None, None)。主/任意线程可调用。"""
        if self._panel is None:
            return (None, None)
        hero = self._hero_field.stringValue() if self._hero_field else ""
        pos = self._pos_field.stringValue() if self._pos_field else ""
        return (hero.strip() or None, pos.strip() or None)

    def set_advice(self, minute: float, text: str):
        """更新建议显示区（线程安全，调度回主线程）。"""
        display = f"[{minute:04.1f}min] {text}"
        self._dispatch(lambda: self._set_advice_text(display))

    def _set_advice_text(self, text: str):
        if self._advice_label is not None:
            self._advice_label.setStringValue_(text)
        if self._panel is not None:
            self._panel.display()

    def show(self, minute: float, text: str):
        self.set_advice(minute, text)

    def _dispatch(self, fn):
        # 尽量回主线程执行；若已在主线程直接执行
        if not _HAS_MAC:
            return
        try:
            if threading.current_thread() is threading.main_thread():
                fn()
            else:
                AppKit.NSRunLoop.mainRunLoop().performBlock_(fn)
        except Exception:
            pass

    def wait_for_start(self, timeout: float = 3600.0) -> bool:
        """阻塞直到用户点了「开始」，或在指定 hero/position 下直接开始。返回 True。"""
        self._clicked_start.wait(timeout)
        return self._clicked_start.is_set()

    # -- 构建面板 --
    def _build(self, hero="", position=""):
        rect = AppKit.NSMakeRect(300, 400, 480, 240)
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setIgnoresMouseEvents_(False)   # 允许交互输入
        panel.setReleasedWhenClosed_(False)
        content = panel.contentView()

        # 背景
        bg = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 480, 240))
        bg.setWantsLayer_(True)
        bg.layer().setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.0, 0.0, 0.0, 0.6).CGColor())
        content.addSubview_(bg)

        def make_label(x, y, w, h, txt, bold=True, size=16, color=None):
            l = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, w, h))
            l.setStringValue_(txt)
            l.setTextColor_(color or AppKit.NSColor.whiteColor())
            l.setBackgroundColor_(AppKit.NSColor.clearColor())
            l.setDrawsBackground_(False)
            l.setBezeled_(False)
            l.setEditable_(False)
            l.setFont_(AppKit.NSFont.boldSystemFontOfSize_(size) if bold else AppKit.NSFont.systemFontOfSize_(size))
            return l

        # 英雄
        content.addSubview_(make_label(20, 200, 60, 24, "英雄:"))
        hero_f = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(80, 202, 160, 24))
        hero_f.setStringValue_(hero)
        hero_f.setBezeled_(True)
        hero_f.setFont_(AppKit.NSFont.systemFontOfSize_(14))
        content.addSubview_(hero_f)
        self._hero_field = hero_f

        # 位置
        content.addSubview_(make_label(250, 200, 60, 24, "位置:"))
        pos_f = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(310, 202, 150, 24))
        pos_f.setStringValue_(position)
        pos_f.setBezeled_(True)
        pos_f.setFont_(AppKit.NSFont.systemFontOfSize_(14))
        content.addSubview_(pos_f)
        self._pos_field = pos_f

        # 开始按钮
        btn = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(20, 150, 440, 40))
        btn.setTitle_("开始输出建议")
        btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        btn.setTarget_(self)
        btn.setAction_("startCoach:")
        content.addSubview_(btn)

        # 建议显示区
        advice = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(20, 20, 440, 120))
        advice.setStringValue_("等待输入英雄/位置后点「开始输出建议」")
        advice.setTextColor_(AppKit.NSColor.whiteColor())
        advice.setBackgroundColor_(AppKit.NSColor.clearColor())
        advice.setDrawsBackground_(False)
        advice.setBezeled_(False)
        advice.setEditable_(False)
        advice.setFont_(AppKit.NSFont.systemFontOfSize_(16))
        advice.setUsesSingleLineMode_(False)
        advice.setWraps_(True)
        content.addSubview_(advice)
        self._advice_label = advice

        self._panel = panel
        panel.orderFrontRegardless()
        return panel

    def open(self, hero="", position=""):
        """显示面板（需在主线程）。返回 self。"""
        self._build(hero, position)
        return self

    @objc.selector  # type: ignore[misc]
    def startCoach_(self, sender):  # noqa: N802
        """NSButton action：开始输出建议。"""
        self._running = True
        self._clicked_start.set()

    def close(self):
        if self._panel is not None:
            self._panel.orderOut_(None)
