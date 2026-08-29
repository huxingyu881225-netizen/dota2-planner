"""Dota 2 Game State Integration (GSI) 服务器。

Dota 2 通过 gamestate_integration_*.cfg 把游戏状态以 JSON POST 到本地端口（默认 6000）。
本模块起一个 HTTP 服务器接收这些 POST，解析出游戏时间与当前英雄，供 coach 做
“从游戏开始自动计时”的时钟，以及自动识别英雄名。

参考字段（dota-ai-coach 同款思路）：
    map.clock_time       —— 游戏时钟时间（秒，游戏开始时从 0 计，比 game_time 更精确）
    map.game_time        —— 兜底用（部分版本/时刻只有 game_time）
    map.game_state       —— DOTA_GAMERULES_STATE_*；GAME_IN_PROGRESS 表示对局中
    hero.info.name       —— 本地玩家英雄 NPC 名，如 npc_dota_hero_juggernaut
    player.team          —— 本地玩家队伍
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional


class GsiState:
    """线程安全地保存最新 GSI 状态。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._game_time: float = 0.0
        self._game_state: str = ""
        self._hero_name: str = ""
        self._team: str = ""
        self._last_update_ts: float = 0.0

    def _now(self) -> float:
        import time
        return time.time()

    def update(self, data: dict[str, Any]) -> None:
        with self._lock:
            m = data.get("map") or {}
            try:
                # 优先用更精确的 clock_time；缺失时回退 game_time
                self._game_time = float(m.get("clock_time", m.get("game_time", 0)) or 0)
            except (TypeError, ValueError):
                self._game_time = 0.0
            self._game_state = str(m.get("game_state", "") or "")

            # 当前本地玩家英雄名：hero.info.name（部分版本 hero.name）
            hero = data.get("hero") or {}
            info = hero.get("info") or {}
            name = info.get("name") or hero.get("name") or ""
            self._hero_name = str(name)

            # 队伍
            player = data.get("player") or {}
            self._team = str(player.get("team", "") or "")

            self._last_update_ts = self._now()

    @property
    def game_time(self) -> float:
        with self._lock:
            return self._game_time

    @property
    def game_state(self) -> str:
        with self._lock:
            return self._game_state

    @property
    def hero_name(self) -> str:
        with self._lock:
            return self._hero_name

    @property
    def team(self) -> str:
        with self._lock:
            return self._team

    @property
    def in_game(self) -> bool:
        """对局进行中（排除英雄选择/等待/结束）。"""
        gs = self.game_state
        # 对局进行中；DOTA_GAMERULES_STATE_GAME_IN_PROGRESS
        return "GAME_IN_PROGRESS" in gs or (gs == "" and self.game_time >= 0)

    @property
    def fresh(self, max_age: float = 35.0) -> bool:
        """GSI 数据是否新（heartbeat 默认 30s，超过 35s 视为失效）。"""
        import time
        return (self._now() - self._last_update_ts) <= max_age

    def to_summary(self) -> str:
        return f"game_time={self.game_time:.0f}s state={self.game_state!r} hero={self.hero_name!r} team={self.team!r}"


class _GSIHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else b""
            if body:
                data = json.loads(body.decode("utf-8", errors="replace"))
                if isinstance(data, dict):
                    # server 持有 state 的引用
                    self.server._gsi_state.update(data)  # type: ignore[attr-defined]
        except Exception:
            pass
        self.send_response(200)
        self.end_headers()

    def do_GET(self):  # noqa
        """健康检查：返回当前 GSI 状态摘要。"""
        summary = getattr(self.server, "_gsi_state", None)  # type: ignore[attr-defined]
        if summary is None:
            text = "{}"
        else:
            import json as _j
            text = _j.dumps({
                "game_time": summary.game_time,
                "game_state": summary.game_state,
                "hero": summary.hero_name,
                "team": summary.team,
                "in_game": summary.in_game,
                "fresh": summary.fresh,
            })
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # noqa: 静默日志
        pass


class GsiServer:
    """在独立线程运行 GSI HTTP 服务器。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 6000, state: Optional[GsiState] = None):
        self.host = host
        self.port = port
        self.state = state or GsiState()
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """启动服务器，返回是否成功监听。"""
        try:
            self._httpd = HTTPServer((self.host, self.port), _GSIHandler)
            self._httpd._gsi_state = self.state  # type: ignore[attr-defined]
            self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._thread.start()
            return True
        except OSError:
            self._httpd = None
            return False

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
