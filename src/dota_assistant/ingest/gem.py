"""gem-dota 本地录像解析——本项目的主/默认数据源。

读取本地 .dem 录像，用 gem.parse() 解析出结构化比赛对象，再定位目标英雄玩家，
产出统一的数据字典供 extractor 抽样（秒级时间序列 + 事件日志）。
"""
from __future__ import annotations

from typing import Any, Optional


class GemSource:
    """主数据源：解析本地 .dem 录像。"""

    name = "gem"

    def __init__(self, replay_path: Optional[str] = None):
        self.replay_path = replay_path

    def fetch(self, replay_path: str, hero: str, position: str, minute_n: int, interval_m: int) -> dict[str, Any]:
        """解析录像，返回含目标玩家对象的数据字典。

        返回结构:
          {match,      # gem 的 ParsedMatch
           players,    # gem 的 ParsedPlayer 列表
           hero, position, minute_n, interval_m,
           player,     # 目标英雄的 ParsedPlayer（未找到则为 None）
          }
        """
        path = self.replay_path or replay_path
        try:
            import gem
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "gem-dota 未安装。请先安装：  uv sync --extra gem"
            ) from e

        parsed = gem.parse(path)
        players = list(getattr(parsed, "players", []) or [])
        player = None
        try:
            player = gem.find_player(parsed, hero)
        except Exception:  # pragma: no cover - 兼容旧版 gem
            # 回退：按英雄名模糊匹配 players
            h = hero.lower().replace(" ", "").replace("-", "").replace("_", "")
            for p in players:
                name = str(getattr(p, "hero_name", "") or "").lower().replace("npc_dota_hero_", "")
                if name.replace("_", "") == h or name.replace(" ", "") == h:
                    player = p
                    break

        return {
            "match": parsed,
            "players": players,
            "hero": hero,
            "position": position,
            "minute_n": minute_n,
            "interval_m": interval_m,
            "player": player,
        }
