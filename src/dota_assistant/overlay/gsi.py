"""Dota 2 Game State Integration (GSI) 服务器。

Dota 2 通过 gamestate_integration_*.cfg 把游戏状态以 JSON POST 到本地端口（默认 6000）。
本模块起一个 HTTP 服务器接收这些 POST，解析出游戏时间/当前英雄/对局ID，供 coach 做
“从游戏开始自动计时”的时钟、自动识别英雄名，以及多局切换时的重置。

参考字段：
    map.clock_time       —— 游戏时钟时间（秒）。可能为负（选人/策略阶段倒计时到 0 才开始）
    map.game_time        —— 兜底时间（部分版本/时刻只有 game_time）
    map.matchid          —— 对局 match id（用于识别是否新开一局）
    map.game_state       —— DOTA_GAMERULES_STATE_*；GAME_IN_PROGRESS 表示对局中
    hero.info.name       —— 本地玩家英雄 NPC 名，如 npc_dota_hero_juggernaut
    player.team          —— 本地玩家队伍
    player.session_num   —— 会话序号（兜底匹配识别）
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
        self._clock_time: float = 0.0
        self._game_time: float = 0.0
        self._coach_time: float = 0.0     # 教练用时间：优先 clock_time，缺失用 game_time
        self._game_state: str = ""
        self._hero_name: str = ""
        self._team: str = ""
        self._match_id: str = ""
        self._session_id: str = ""
        self._last_update_ts: float = 0.0

    def _now(self) -> float:
        import time
        return time.time()

    def update(self, data: dict[str, Any]) -> None:
        with self._lock:
            m = data.get("map") or {}
            try:
                self._clock_time = float(m.get("clock_time", 0) or 0)
            except (TypeError, ValueError):
                self._clock_time = 0.0
            try:
                self._game_time = float(m.get("game_time", 0) or 0)
            except (TypeError, ValueError):
                self._game_time = 0.0
            # coach_time 优先 clock_time，缺失用 game_time
            if "clock_time" in m and m.get("clock_time") is not None:
                self._coach_time = self._clock_time
            else:
                self._coach_time = self._game_time
            self._game_state = str(m.get("game_state", "") or "")

            # match/session 识别
            self._match_id = str(m.get("matchid", "") or "") or str(m.get("match_id", "") or "")
            player = data.get("player") or {}
            self._session_id = str(player.get("session_num", "") or "")

            # 当前本地玩家英雄名：hero.info.name（部分版本 hero.name）
            hero = data.get("hero") or {}
            info = hero.get("info") or {}
            name = info.get("name") or hero.get("name") or ""
            self._hero_name = str(name)

            # 队伍
            self._team = str(player.get("team", "") or "")

            self._last_update_ts = self._now()

    @property
    def clock_time(self) -> float:
        with self._lock:
            return self._clock_time

    @property
    def game_time(self) -> float:
        with self._lock:
            return self._game_time

    @property
    def coach_time(self) -> float:
        """教练用时间：优先 clock_time，缺失回退 game_time。"""
        with self._lock:
            return self._coach_time

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
    def match_id(self) -> str:
        with self._lock:
            return self._match_id

    @property
    def session_id(self) -> str:
        with self._lock:
            return self._session_id

    @property
    def in_game(self) -> bool:
        """对局进行中（排除英雄选择/等待/结束）。"""
        gs = self.game_state
        return "GAME_IN_PROGRESS" in gs or (gs == "" and self.coach_time >= 0)

    @property
    def fresh(self, max_age: float = 35.0) -> bool:
        """GSI 数据是否新（heartbeat 默认 30s，超过 35s 视为失效）。"""
        import time
        return (self._now() - self._last_update_ts) <= max_age

    def to_summary(self) -> str:
        return (f"coach_time={self.coach_time:.0f}s state={self.game_state!r} "
                f"hero={self.hero_name!r} team={self.team!r} match={self.match_id!r}")


class _GSIHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else b""
            if body:
                data = json.loads(body.decode("utf-8", errors="replace"))
                if isinstance(data, dict):
                    self.server._gsi_state.update(data)  # type: ignore[attr-defined]
        except Exception:
            pass
        self.send_response(200)
        self.end_headers()

    def do_GET(self):  # noqa
        summary = getattr(self.server, "_gsi_state", None)  # type: ignore[attr-defined]
        if summary is None:
            text = "{}"
        else:
            import json as _j
            text = _j.dumps({
                "clock_time": summary.clock_time,
                "game_time": summary.game_time,
                "coach_time": summary.coach_time,
                "game_state": summary.game_state,
                "hero": summary.hero_name,
                "team": summary.team,
                "match_id": summary.match_id,
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
