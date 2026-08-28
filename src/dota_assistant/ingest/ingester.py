"""灌入服务：解析 .dem -> 抽取 -> 写入 SQLite。"""
from __future__ import annotations

from typing import Optional

from dota_assistant.core.models import MatchMeta
from dota_assistant.db.database import connect, init_schema
from dota_assistant.db.repo import Repo
from dota_assistant.ingest.extractor import extract
from dota_assistant.ingest.gem import GemSource


class Ingester:
    def __init__(self, conn=None, source=None):
        self.conn = conn
        self.source = source or GemSource()

    def run(
        self,
        replay_path: str,
        hero: str,
        position: str,
        minute_n: int = 10,
        interval_m: int = 30,
        result: Optional[str] = None,
    ) -> tuple[int, int]:
        """返回 (match_ref, 写入样本数)。"""
        data = self.source.fetch(replay_path, hero, position, minute_n, interval_m)
        if data.get("player") is None:
            raise ValueError(f"录像中未找到英雄 {hero!r} 的玩家。")

        samples = extract(data, hero, position, minute_n, interval_m)
        if not samples:
            raise ValueError("未产出样本（请检查 英雄/位置 与 前N分钟 参数）。")

        meta = MatchMeta(
            match_id=str(replay_path),
            source=self.source.name,
            hero=hero,
            position=position,
            minute_n=minute_n,
            interval_m=interval_m,
            result=result,
        )
        with Repo(self.conn) as repo:
            match_ref = repo.insert_match(meta)
            inserted = repo.insert_samples(match_ref, samples)
        return match_ref, inserted
