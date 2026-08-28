"""Domain models for dota_assistant."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MatchMeta:
    match_id: str
    source: str  # 'opendota' | 'gem' | 'manual'
    hero: str
    position: str
    minute_n: int
    interval_m: int
    result: Optional[str] = None  # 'win' | 'loss'

    def row(self) -> tuple:
        return (
            self.match_id,
            self.source,
            self.hero,
            self.position,
            self.minute_n,
            self.interval_m,
            self.result,
        )


@dataclass
class Sample:
    """One behavior observation at a point in time (every M seconds)."""

    hero: str
    position: str
    t_sec: int
    t_min: float
    behavior: str
    cs: Optional[int] = None
    gpm: Optional[int] = None
    xpm: Optional[int] = None
    networth: Optional[int] = None
    kills: Optional[int] = None
    deaths: Optional[int] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_row(self, match_ref: int) -> tuple:
        return (
            match_ref,
            self.hero,
            self.position,
            self.t_sec,
            self.t_min,
            self.behavior,
            self.cs,
            self.gpm,
            self.xpm,
            self.networth,
            self.kills,
            self.deaths,
            self.pos_x,
            self.pos_y,
            json_dumps(self.extra),
        )


@dataclass
class Advice:
    """Editable reference advice for (hero, position) in a time window."""

    hero: str
    position: str
    t_start_min: float
    t_end_min: float
    advice: str
    source: Optional[str] = None
    id: Optional[int] = None
    updated_at: Optional[str] = None


@dataclass
class Deviation:
    """One detected mismatch between a replay and the DB reference."""

    t_min: float
    field: str  # e.g. 'cs', 'behavior', 'gpm', 'deaths'
    actual: Any
    reference: Any
    direction: str  # 'higher' | 'lower' | 'different'
    outcome: str = "neutral"  # 'good' | 'bad' | 'neutral'
    note: str = ""


@dataclass
class DiffReport:
    hero: str
    position: str
    skipped: bool = False
    skip_reason: str = ""
    deviations: list[Deviation] = field(default_factory=list)
    summary: str = ""

    @property
    def good_count(self) -> int:
        return sum(1 for d in self.deviations if d.outcome == "good")

    @property
    def bad_count(self) -> int:
        return sum(1 for d in self.deviations if d.outcome == "bad")

    def to_dict(self) -> dict:
        return {
            "hero": self.hero,
            "position": self.position,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "good_count": self.good_count,
            "bad_count": self.bad_count,
            "deviations": [
                {
                    "t_min": d.t_min,
                    "field": d.field,
                    "actual": d.actual,
                    "reference": d.reference,
                    "direction": d.direction,
                    "outcome": d.outcome,
                    "note": d.note,
                }
                for d in self.deviations
            ],
            "summary": self.summary,
        }


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)
