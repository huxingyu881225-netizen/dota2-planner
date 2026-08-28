"""macOS floating overlay via NSPanel (pyobjc).

Reference: dota-ai-coach floating window. Always-on-top, non-activating,
borderless. If pyobjc is unavailable we raise a user-friendly error and the CLI
falls back to terminal mode.
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
    """Minimal always-on-top label window. Call show() from main thread."""

    def __init__(self):
        if not _HAS_MAC:
            raise RuntimeError("pyobjc-framework-Cocoa not available; use terminal mode")
        self._label = None
        self._panel = None

    def _build(self, text: str):
        rect = AppKit.NSMakeRect(200, 300, 460, 90)
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setIgnoresMouseEvents_(True)
        panel.setReleasedWhenClosed_(False)

        label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(10, 10, 440, 70)
        )
        label.setStringValue_(text)
        label.setTextColor_(AppKit.NSColor.whiteColor())
        label.setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.0, 0.0, 0.0, 0.55,
        ))
        label.setDrawsBackground_(True)
        label.setFont_(AppKit.NSFont.boldSystemFontOfSize_(20))
        label.setEditable_(False)
        label.setBezeled_(False)
        panel.contentView().addSubview_(label)

        self._label = label
        self._panel = panel
        panel.orderFrontRegardless()

    def show(self, minute: float, text: str):
        if self._panel is None:
            self._build(text)
            return
        display = f"[{minute:04.1f}min] {text}"
        self._label.setStringValue_(display)
        self._panel.display()

    def close(self):
        if self._panel is not None:
            self._panel.orderOut_(None)
