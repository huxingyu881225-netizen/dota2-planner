"""macOS 浮窗（NSPanel, pyobjc），参考 dota-ai-coach。

与 coach 的交互：
- 英雄名：由 GSI 感知后自动显示在浮窗（只读，用户无需输入英雄）。
- 位置：浮窗用下拉选择库里该英雄已有的位置。
- 只有当 (英雄, 位置) 在 advice 库里有数据时，coach 才按游戏时间输出建议。

若 pyobjc 不可用则抛错，由 CLI 降级到终端模式。
"""
from __future__ import annotations

import threading
from typing import Optional

try:
    import AppKit
    _HAS_MAC = True
except Exception:  # pragma: no cover
    _HAS_MAC = False


class MacOverlay:
    POSITIONS = ["carry", "mid", "offline", "offlane_support", "safelane_support"]

    def __init__(self):
        if not _HAS_MAC:
            raise RuntimeError("pyobjc-framework-Cocoa not available; use terminal mode")
        self._panel = None
        self._hero_label = None
        self._pos_popup = None
        self._advice_label = None
        self._clicked_start = threading.Event()
        self._lock = threading.Lock()

    # ---- 线程安全读取 GSI 英雄 & 位置选择 ----
    def set_hero_from_gsi(self, hero: str):
        """由 GSI 更新英雄显示（主线程调度）。"""
        if hero:
            self._dispatch(lambda: self._hero_label.setStringValue_(hero) if self._hero_label else None)

    def selected_position(self) -> Optional[str]:
        if self._pos_popup is None:
            return None
        return self._pos_popup.titleOfSelectedItem()

    def ask_position(self, hero: str, options: list[str]) -> Optional[str]:
        """让用户在浮窗下拉里选位置（阻塞直到选择）。返回所选或 None。"""
        self._dispatch(lambda: self._load_positions(options))
        self._clicked_start.clear()
        self._dispatch(lambda: self._set_status_text(f"英雄 {hero} 有多个位置，请选择并点击「开始」"))
        self._clicked_start.wait(timeout=3600)
        return self.selected_position()

    def _load_positions(self, options: list[str]):
        if self._pos_popup is not None:
            self._pos_popup.removeAllItems()
            self._pos_popup.addItemsWithTitles_(options)

    # ---- 显示 advice ----
    def show(self, minute: float, text: str):
        display = f"[{minute:04.1f}min] {text}"
        self._dispatch(lambda: self._set_status_text(display))

    def _set_status_text(self, text: str):
        if self._advice_label is not None:
            self._advice_label.setStringValue_(text)
        if self._panel is not None:
            self._panel.display()

    def _dispatch(self, fn):
        if not _HAS_MAC:
            return
        try:
            if threading.current_thread() is threading.main_thread():
                fn()
            else:
                AppKit.NSRunLoop.mainRunLoop().performBlock_(fn)
        except Exception:
            pass

    # ---- 面板构建 ----
    def open(self, hero: str = "", position: str = ""):
        self._build(hero, position)
        return self

    def _build(self, hero: str, position: str):
        import objc
        rect = AppKit.NSMakeRect(300, 400, 480, 230)
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False)
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setIgnoresMouseEvents_(False)
        panel.setReleasedWhenClosed_(False)
        content = panel.contentView()

        bg = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 480, 230))
        bg.setWantsLayer_(True)
        bg.layer().setBackgroundColor_(
            AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.6).CGColor())
        content.addSubview_(bg)

        def make_label(x, y, w, h, txt, size=16):
            l = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, w, h))
            l.setStringValue_(txt)
            l.setTextColor_(AppKit.NSColor.whiteColor())
            l.setBackgroundColor_(AppKit.NSColor.clearColor())
            l.setDrawsBackground_(False)
            l.setBezeled_(False)
            l.setEditable_(False)
            l.setFont_(AppKit.NSFont.boldSystemFontOfSize_(size))
            return l

        # 英雄（GSI 只读显示）
        content.addSubview_(make_label(20, 196, 60, 24, "英雄:"))
        hero_l = make_label(80, 198, 200, 24, hero or "(等待 GSI)…")
        content.addSubview_(hero_l)
        self._hero_label = hero_l

        # 位置（下拉）
        content.addSubview_(make_label(20, 166, 60, 24, "位置:"))
        popup = AppKit.NSPopUpButton.alloc().initWithFrame_(AppKit.NSMakeRect(80, 168, 160, 26))
        popup.removeAllItems()
        popup.addItemsWithTitles_(self.POSITIONS if position not in self.POSITIONS else [position])
        if position in self.POSITIONS:
            popup.selectItemWithTitle_(position)
        content.addSubview_(popup)
        self._pos_popup = popup

        # 开始
        btn = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(20, 120, 440, 40))
        btn.setTitle_("开始输出建议")
        btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        btn.setTarget_(self)
        btn.setAction_("startCoach:")
        content.addSubview_(btn)

        # 建议显示区
        advice = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(20, 10, 440, 100))
        advice.setStringValue_("等待…")
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

    @objc.selector
    def startCoach_(self, sender):  # noqa: N802
        self._clicked_start.set()

    def close(self):
        if self._panel is not None:
            self._panel.orderOut_(None)
