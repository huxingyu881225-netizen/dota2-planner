"""数据源抽象（当前主力 = gem-dota 本地 .dem）。"""
from __future__ import annotations

from .gem import GemSource

# gem-dota 为主；OpenDota 已降级为可选（保留 opendota.py 供需要时用）

SOURCE_NAMES = ("gem",)


def make_source(source_name: str, replay_path: str | None = None):
    """返回一个数据源实例。当前唯一正式源为标准：gem-dota。

    `source_name` 仅接受 "gem"。保留 opendota 作为预留，但 CLI 不再默认暴露。
    """
    name = (source_name or "gem").lower()
    if name == "gem":
        return GemSource(replay_path)
    from .opendota import OpenDotaSource
    return OpenDotaSource()  # 预留：联机查 OpenDota 用
