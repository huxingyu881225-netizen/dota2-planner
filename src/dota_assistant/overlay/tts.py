"""TTS 语音播报（macOS 优先用系统 /usr/bin/say，无需新增依赖）。

- speak() 异步启动播报，不阻塞调用方（coach 主循环）。
- 新播报会打断上一条未播完的（kill 前一个 say 子进程）。
- 非 macOS（或没有 say）自动 no-op，预留扩展（如接入其它引擎只需覆写 _run_say）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from typing import Optional


def _say_path() -> Optional[str]:
    """返回系统 say 可执行文件的路径；找不到返回 None。"""
    if sys.platform != "darwin":
        return None
    p = shutil.which("say")
    if p:
        return p
    # 兜底：系统自带路径
    default = "/usr/bin/say"
    return default if os.path.exists(default) else None


class TtsSpeaker:
    """异步语音播报器。当前进程持有正在播放的子进程，新播报打断旧的。"""

    def __init__(self, rate: int = 200):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._say = _say_path()
        self._rate = rate

    @property
    def available(self) -> bool:
        return self._say is not None

    def speak(self, text: str) -> bool:
        """异步播报文本。返回是否真正开始了播报（False = 平台不支持/失败）。"""
        if not text or not self.available:
            return False
        # 打断上一条未播完的
        with self._lock:
            self._kill_current()
            try:
                proc = subprocess.Popen(
                    [self._say, "-r", str(self._rate), "--", self._clean(text)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._proc = proc
                return True
            except Exception:
                self._proc = None
                return False

    def stop(self):
        """停止当前播报（如程序退出时）。"""
        with self._lock:
            self._kill_current()

    def _kill_current(self):
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    @staticmethod
    def _clean(text: str) -> str:
        """去掉可能影响语音的修饰符（保留中文建议主体）。"""
        return text.strip()

# 单例便于复用（可选）
_default: Optional[TtsSpeaker] = None


def get_speaker() -> TtsSpeaker:
    global _default
    if _default is None:
        _default = TtsSpeaker()
    return _default
