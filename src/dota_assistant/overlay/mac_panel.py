"""macOS 浮窗（NSPanel, pyobjc），参考 dota-ai-coach。

架构：
- 主线程跑 `NSApplication.run()`（AppKit 事件循环），窗口才能显示并响应事件。
- coach 逻辑跑在后台线程，UI 更新通过 performSelectorOnMainThread 回主线程。

交互：
- 英雄名：由 GSI 感知后只读显示在浮窗（无需输入）。
- 位置：浮窗下拉选择库里该英雄已有的位置。
- 只有当 (英雄, 位置) 在 advice 库里有数据时，coach 才按游戏时间输出建议。
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import objc
import AppKit


class _ButtonTarget(AppKit.NSObject):
    """独立的 ObjC target，仅暴露按钮 action，避免与面板方法的 selector 冲突。"""

    def initWithCallback_(self, cb: Callable[[], None]):
        self = objc.super(_ButtonTarget, self).init()
        if self is None:
            return None
        self._cb = cb
        return self

    @objc.selector
    def startCoach_(self, sender):  # noqa: N802
        try:
            self._cb()
        except Exception:
            pass


class MacOverlay:
    """可输入位置的 macOS 置顶浮窗（普通 Python 类，UI 按钮用独立 ObjC target）。"""

    POSITIONS = ["carry", "mid", "offline", "offlane_support", "safelane_support"]

    def __init__(self):
        import os
        self._panel = None
        self._hero_label = None
        self._pos_popup = None
        self._advice_label = None
        self._clicked_start = threading.Event()
        self._button_target = None
        # GUI 模式下总是让用户在浮窗确认位置（即使库里只有一个位置）
        self.requires_position_confirmation = True
        # 鼠标穿透初始值：默认 False（可交互）；可用环境变量 DOTA_OVERLAY_PASSTHROUGH=1 设为穿透
        self._mouse_passthrough = bool(os.environ.get("DOTA_OVERLAY_PASSTHROUGH", ""))
        self._shown_hero = None              # 已显示过的英雄（去重）
        self._hidden = False                 # F9 隐藏状态
        self._key_monitor = None             # NSEvent 全局热键监听

    # ---------- UI 更新（任意线程可调用） ----------
    def set_hero_from_gsi(self, hero: str):
        if hero:
            self._main(lambda: self._sync_display_hero(hero))

    def start_advice_mode(self):
        """进入出建议模式（兼容 coach 调用）。鼠标穿透由用户用 F10 手动控制，不自动切换。"""
        # item 6：点「开始」后不再自动 setIgnoresMouseEvents_(True)，交给 F10 切换
        pass

    def _set_mouse_passthrough(self, passthrough: bool):
        """设置鼠标是否穿透（F10 手动/初始化）。passthrough=True 不挡游戏操作。"""
        def set_(flag: bool):
            if self._panel is not None:
                self._panel.setIgnoresMouseEvents_(flag)
                self._mouse_passthrough = flag
        if self._panel is not None:
            self._main(lambda: set_(passthrough))

    def toggle_mouse_passthrough(self):
        """F10：切换 鼠标可点击 <-> 鼠标穿透。返回切换后的状态。"""
        self._mouse_passthrough = not self._mouse_passthrough
        self._set_mouse_passthrough(self._mouse_passthrough)
        return self._mouse_passthrough

    def _sync_display_hero(self, hero: str):
        """去重显示英雄：只在该英雄变化时才更新浮窗文本（避免一直刷“等待 GSI”）。"""
        if hero != self._shown_hero:
            self._shown_hero = hero
            self._set_hero_text(hero)

    def selected_position(self) -> Optional[str]:
        return self._pos_popup.titleOfSelectedItem() if self._pos_popup else None

    def ask_position(self, hero: str, options: list[str]) -> Optional[str]:
        """让用户在浮窗下拉里选位置（阻塞直到选择）。返回所选或 None。

        等待期间恢复鼠标交互（setIgnoresMouseEvents_(False)），让用户能点下拉/开始按钮。
        """
        self._set_mouse_passthrough(False)  # 恢复交互
        self._main(lambda: self._load_positions(options))
        self._clicked_start.clear()
        self._main(lambda: self._set_status_text(f"英雄 {hero} 有多个位置，请选择后点「开始」"))
        self._clicked_start.wait(timeout=3600)
        return self.selected_position()

    def show(self, minute: float, text: str):
        display = f"[{minute:04.1f}min] {text}"
        self._main(lambda: self._set_status_text(display))

    def _main(self, fn):
        """调度到主线程执行：主线程直接调；子线程排入主 runloop(NSApp.run 在跑时执行)。"""
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            try:
                AppKit.NSRunLoop.mainRunLoop().performBlock_(fn)
            except Exception:
                pass

    # ---------- 面板构建（须在主线程调用） ----------
    def open(self, hero: str = "", position: str = ""):
        self._build(hero, position)
        return self

    def _build(self, hero: str, position: str):
        import os
        # 窗口尺寸
        W, H = 480, 230
        # 位置：优先 DOTA_OVERLAY_X / DOTA_OVERLAY_Y；否则默认右上角
        x_env = os.environ.get("DOTA_OVERLAY_X")
        y_env = os.environ.get("DOTA_OVERLAY_Y")
        if x_env and y_env:
            try:
                x, y = int(x_env), int(y_env)
            except ValueError:
                x = y = None
        else:
            x = y = None
        if x is None or y is None:
            scr = AppKit.NSScreen.mainScreen().frame()
            x = int(scr.origin.x + scr.size.width - W - 20)
            y = int(scr.origin.y + scr.size.height - H - 20)
        rect = AppKit.NSMakeRect(x, y, W, H)
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False)
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setIgnoresMouseEvents_(False)
        panel.setReleasedWhenClosed_(False)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
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
        if position in self.POSITIONS:
            popup.addItemsWithTitles_(self.POSITIONS)
            popup.selectItemWithTitle_(position)
        else:
            popup.addItemsWithTitles_(self.POSITIONS)
        content.addSubview_(popup)
        self._pos_popup = popup

        # 开始按钮（用独立 ObjC target 触发事件）
        btn = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(20, 120, 440, 40))
        btn.setTitle_("开始输出建议")
        btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        target = _ButtonTarget.alloc().initWithCallback_(self._on_start)
        btn.setTarget_(target)
        btn.setAction_("startCoach:")
        content.addSubview_(btn)
        self._button_target = target

        # 建议显示区（换行在 cell 上设置）
        advice = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(20, 10, 440, 100))
        advice.setStringValue_("等待…")
        advice.setTextColor_(AppKit.NSColor.whiteColor())
        advice.setBackgroundColor_(AppKit.NSColor.clearColor())
        advice.setDrawsBackground_(False)
        advice.setBezeled_(False)
        advice.setEditable_(False)
        advice.setSelectable_(False)
        advice.setFont_(AppKit.NSFont.systemFontOfSize_(16))
        advice.setUsesSingleLineMode_(False)
        advice.cell().setWraps_(True)
        advice.cell().setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        advice.cell().setTruncatesLastVisibleLine_(False)
        content.addSubview_(advice)
        self._advice_label = advice

        self._panel = panel
        panel.makeKeyAndOrderFront_(None)
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    # ---------- 事件循环 / 关闭 ----------
    def run(self):
        """阻塞运行 AppKit 事件循环（须在主线程调用）。注册 F9 隐藏/显示热键。"""
        self._register_hotkey()
        AppKit.NSApplication.sharedApplication().run()

    def _register_hotkey(self):
        """监听 F9/Fn+F9 隐藏显示；F10/Fn+F10 切换鼠标穿透。需辅助功能权限。"""
        from AppKit import NSEvent, NSKeyDownMask
        F9 = 97
        F10 = 85

        def handler(ev):
            try:
                kc = ev.keyCode()
                if kc == F9:
                    self._main(self.toggle_visible)
                elif kc == F10:
                    def _do():
                        state = self.toggle_mouse_passthrough()
                        self._set_status_text("鼠标穿透" if state else "鼠标可点击")
                    self._main(_do)
            except Exception:
                pass
            return ev

        self._key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, handler)

    def toggle_visible(self):
        """F9：隐藏/显示浮窗。"""
        if self._panel is None:
            return
        if self._hidden:
            self._panel.orderFrontRegardless()
            self._hidden = False
        else:
            self._panel.orderOut_(None)
            self._hidden = True

    def stop_app(self):
        AppKit.NSApplication.sharedApplication().stop_(None)

    def close(self):
        if self._panel is not None:
            self._panel.orderOut_(None)

    # ---------- 内部 ----------
    def _on_start(self):
        self._clicked_start.set()
        # item 6：不自动改鼠标穿透（由用户 F10 手动控制）

    def _set_hero_text(self, hero: str):
        if self._hero_label is not None:
            self._hero_label.setStringValue_(hero)
            self._panel.display()

    def _load_positions(self, options: list[str]):
        if self._pos_popup is not None:
            self._pos_popup.removeAllItems()
            self._pos_popup.addItemsWithTitles_(options)

    def _set_status_text(self, text: str):
        if self._advice_label is not None:
            self._advice_label.setStringValue_(text)
        if self._panel is not None:
            self._panel.display()
