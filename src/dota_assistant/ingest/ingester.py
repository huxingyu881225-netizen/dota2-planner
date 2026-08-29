"""灌入服务：解析 .dem -> 抽取窗口 -> (可选 LLM) 生成核心策略 -> 写入 SQLite。"""
from __future__ import annotations

import os
from typing import Optional

from dota_assistant.core.models import MatchMeta, Sample
from dota_assistant.db.database import connect, init_schema
from dota_assistant.db.repo import Repo
from dota_assistant.ingest.extractor import extract, extract_windows
from dota_assistant.ingest.gem import GemSource
from dota_assistant.llm.strategy import generate_strategy_batch


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
        use_llm: Optional[bool] = None,
    ) -> tuple[int, int]:
        """返回 (match_ref, 写入样本数, advice 初始化条数)。

        use_llm=None 时自动判断：设了 DOTA_LLM_API_KEY 则用 LLM，否则回退模板。
        use_llm=True 强制 LLM（无 key 会直接回退模板并静默）。
        use_llm=False 强制模板。
        """
        data = self.source.fetch(replay_path, hero, position, minute_n, interval_m)
        if data.get("player") is None:
            raise ValueError(f"录像中未找到英雄 {hero!r} 的玩家。")

        windows = extract_windows(data, minute_n, interval_m)
        if not windows:
            raise ValueError("未产出窗口（请检查 英雄/位置 与 前N分钟 参数）。")

        # 生成策略文本（LLM 或模板）
        if use_llm is not False:
            strategies = generate_strategy_batch(windows, hero, position)
        else:
            from dota_assistant.core.behavior import build as build_template
            strategies = [build_template(w, position) for w in windows]

        samples = []
        for metrics, behavior in zip(windows, strategies):
            samples.append(Sample(
                hero=hero,
                position=position,
                t_sec=int(metrics["t_sec"]),
                t_min=metrics["t_min"],
                behavior=behavior,
                cs=metrics.get("cs"),
                gpm=metrics.get("gpm"),
                xpm=metrics.get("xpm"),
                networth=metrics.get("networth"),
                kills=metrics.get("kills_total"),
                deaths=metrics.get("deaths"),
                pos_x=metrics.get("pos_x"),
                pos_y=metrics.get("pos_y"),
                extra=metrics,
            ))

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
            # 用样本策略初始化 advice（每 interval_m 秒一条，可后续人工编辑）
            advice_count = repo.init_advice_from_samples(hero, position, source=str(replay_path), interval_m=interval_m)
        return match_ref, inserted, advice_count
