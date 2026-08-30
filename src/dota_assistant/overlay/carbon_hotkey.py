"""Carbon RegisterEventHotKey 全局热键（macOS）。

用 ctypes 直接调用 Carbon framework：
- RegisterEventHotKey 注册系统级热键，**不依赖辅助功能权限**，全局生效（游戏前台也能收到）。
- 相比 AppKit addGlobalMonitor（需辅助功能权限）更可靠。

用法：
    hk = CarbonHotkey()
    hk.set_callback(lambda key: print("hotkey", key))
    hk.register(101, "F9")     # F9
    hk.register(109, "F10")    # F10
    hk.install()               # 安装事件处理器（须在事件循环运行前）
"""
from __future__ import annotations

import ctypes
import ctypes.util
import threading
from typing import Callable, Optional

_CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"

# 常量（按 macOS SDK CarbonEvents.h 的准确值）
_kEventClassKeyboard = 0x6B657962   # 'keyb' — kEventClassKeyboard
_kEventHotKeyPressed = 5            # kEventHotKeyPressed
_kEventParamDirectObject = 0x2D2D2D2D  # '----' — kEventParamDirectObject
typeEventHotKeyID = 0x686B6964      # 'hkid' — typeEventHotKeyID（EventHotKeyID 参数类型）
_kEventHotKeyID = typeEventHotKeyID # 别名

# EventTypeSpec { class, kind }
class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class CarbonHotkey:
    """注册并分发全局热键（F9=101, F10=109 等）。"""

    def __init__(self):
        self._carbon = ctypes.cdll.LoadLibrary(_CARBON)
        self._setup_bindings()
        self._hotkey_refs: dict[str, ctypes.c_void_p] = {}
        self._handler_ref: Optional[ctypes.c_void_p] = None
        self._callbacks: dict[int, Callable[[], None]] = {}   # id -> fn
        self._cb = None  # 持有 CFUNCTYPE 引用防止 GC
        self._lock = threading.Lock()
        self._installed = False

    def _setup_bindings(self):
        """给 Carbon 函数设置 argtypes/restype，防止 64 位指针截断崩溃。"""
        c = self._carbon
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32,  # inHotKeyCode
            ctypes.c_uint32,  # inHotKeyModifiers
            ctypes.c_void_p,  # EventHotKeyID* (byref)
            ctypes.c_void_p,  # inTarget
            ctypes.c_uint32,  # inOptions
            ctypes.c_void_p,  # EventHotKeyRef* (out)
        ]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.InstallEventHandler.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p,
        ]
        c.InstallEventHandler.restype = ctypes.c_int32
        # OSStatus GetEventParameter(EventRef, EventParamName, EventParamType,
        #                            EventParamType* outActualType, UInt32 inBufferSize,
        #                            void* outData, UInt32* outActualSize)
        c.GetEventParameter.argtypes = [
            ctypes.c_void_p,    # inEvent
            ctypes.c_uint32,    # inName ('----')
            ctypes.c_uint32,    # inType ('hkid')
            ctypes.c_void_p,    # outActualType (可 NULL)
            ctypes.c_uint32,    # inBufferSize (UInt32)
            ctypes.c_void_p,    # outData
            ctypes.c_void_p,    # outActualSize (UInt32*)
        ]
        c.GetEventParameter.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        c.UnregisterEventHotKey.restype = ctypes.c_int32
        c.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        c.RemoveEventHandler.restype = ctypes.c_int32

    def set_callback(self, fn: Callable[[str], None]):
        """设置回调 fn(key_name)，如 fn('F9')。"""
        self._user_fn = fn

    def register(self, key_code: int, name: str, modifiers: int = 0) -> bool:
        """注册单个热键。key_code 为虚拟键码（F9=101, F10=109）。返回是否成功。"""
        hid = _EventHotKeyID()
        hid.signature = 0x444F5441  # 'DOTA'
        hid.id = key_code
        out_ref = ctypes.c_void_p()
        # OSStatus RegisterEventHotKey(UInt32 inHotKeyCode, UInt32 inHotKeyModifiers,
        #                              EventHotKeyID inHotKeyID, EventTargetRef inTarget,
        #                              OptionBits inOptions, EventHotKeyRef *outRef)
        target = self._carbon.GetApplicationEventTarget()
        status = self._carbon.RegisterEventHotKey(
            ctypes.c_uint32(key_code),
            ctypes.c_uint32(modifiers),
            ctypes.byref(hid),
            target,
            ctypes.c_uint32(0),
            ctypes.byref(out_ref),
        )
        if status == 0 and out_ref.value:
            self._hotkey_refs[name] = out_ref
            self._callbacks[key_code] = lambda n=name: self._emit(n)
            return True
        return False

    def _emit(self, name: str):
        fn = getattr(self, "_user_fn", None)
        if fn:
            try:
                fn(name)
            except Exception:
                pass

    def install(self) -> bool:
        """安装事件处理器（须在 app 事件循环前调用）。返回是否成功。"""
        if self._installed:
            return True
        spec = _EventTypeSpec()
        spec.eventClass = _kEventClassKeyboard
        spec.eventKind = _kEventHotKeyPressed

        # EventHandlerUPP: OSStatus (*)(EventHandlerCallRef, EventRef, void*)
        CB = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

        def handler(callref, eventref, userdata):
            try:
                # 从事件里取 EventHotKeyID（kEventParamDirectObject, typeEventHotKeyID）
                hid = _EventHotKeyID()
                size = ctypes.c_uint32(ctypes.sizeof(hid))       # UInt32*
                status = self._carbon.GetEventParameter(
                    ctypes.c_void_p(eventref),                   # inEvent
                    ctypes.c_uint32(_kEventParamDirectObject),   # inName '----'
                    ctypes.c_uint32(typeEventHotKeyID),          # inType 'hkid'
                    None,                                        # outActualType
                    ctypes.c_uint32(ctypes.sizeof(hid)),         # inBufferSize (UInt32)
                    ctypes.byref(hid),                           # outData
                    ctypes.byref(size),                          # outActualSize
                )
                if status == 0:
                    fn = self._callbacks.get(hid.id)
                    if fn:
                        fn()
            except Exception:
                pass
            return 0

        cf = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        self._cb = cb = cf(handler)
        handler_ref = ctypes.c_void_p()
        target = self._carbon.GetApplicationEventTarget()
        status = self._carbon.InstallEventHandler(
            target,
            cb,
            1,
            ctypes.byref(spec),
            None,
            ctypes.byref(handler_ref),
        )
        self._installed = (status == 0)
        if self._installed:
            self._handler_ref = handler_ref
        return self._installed

    def unregister_all(self):
        """注销所有热键与处理器。"""
        for name, ref in self._hotkey_refs.items():
            try:
                self._carbon.UnregisterEventHotKey(ref)
            except Exception:
                pass
        self._hotkey_refs.clear()
        if self._handler_ref:
            try:
                self._carbon.RemoveEventHandler(self._handler_ref)
            except Exception:
                pass
            self._handler_ref = None
        self._installed = False
