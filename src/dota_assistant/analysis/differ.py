"""Post-match diff engine (requirement 3).

Compares one replay's sampled behavior against the DB reference for the same
(hero, position) and judges whether deviations led to good or bad outcomes.

If the DB has no samples for (hero, position), returns a skipped report.
"""
from __future__ import annotations

import statistics
from typing import Any, Optional

from dota_assistant.core.models import Deviation, DiffReport, Sample
from dota_assistant.db.repo import Repo

# Thresholds (fractions) for flagging a field deviation
_CS_PCT = 0.25        # CS off by >=25% of reference
_GPM_PCT = 0.15
_DEATHS_ABS = 2


class OutcomeJudger:
    """Decides whether a deviation was good or bad.

    Default heuristic: compare this replay's field against the reference and,
    using the match's final result as a weak signal, label direction.
    Externally you can swap this for an LLM-backed judger.
    """

    def judge(self, match_result: Optional[str], field: str, direction: str) -> str:
        # Higher is better for farming fields unless it's deaths.
        if field == "deaths":
            return "good" if direction == "lower" else "bad"
        if direction == "higher":
            return "good"
        if direction == "lower":
            return "bad"
        return "neutral"


class Differ:
    def __init__(self, repo: Repo, judger: Optional[OutcomeJudger] = None, tolerance_pct: float = 0.2):
        self.repo = repo
        self.judger = judger or OutcomeJudger()
        self.tolerance = tolerance_pct

    def _reference_bounds(self, hero: str, position: str) -> Optional[dict[int, dict[str, Any]]]:
        """Aggregate DB samples into per-minute reference (mean + stdev)."""
        rows = self.repo.samples_by_hero_position(hero, position)
        if not rows:
            return None
        by_min: dict[int, list] = {}
        for r in rows:
            by_min.setdefault(int(r["t_min"]), []).append(r)
        ref: dict[int, dict[str, Any]] = {}
        for minute, group in by_min.items():
            def avg(key):
                vals = [g[key] for g in group if g[key] is not None]
                return statistics.mean(vals) if vals else None
            ref[minute] = {
                "cs_mean": avg("cs"),
                "gpm_mean": avg("gpm"),
                "n_samples": len(group),
            }
        return ref

    def compare(self, samples: list[Sample], hero: str, position: str, match_result: Optional[str] = None) -> DiffReport:
        report = DiffReport(hero=hero, position=position)
        ref = self._reference_bounds(hero, position)
        if ref is None:
            report.skipped = True
            report.skip_reason = (
                f"数据库中没有 {hero}/{position} 的参考样本，已跳过。"
                f"请先用 `dota ingest` 灌入该英雄/位置的数据。"
            )
            return report

        # group actual samples by minute
        by_min: dict[int, list[Sample]] = {}
        for s in samples:
            by_min.setdefault(int(s.t_min), []).append(s)

        for minute, group_sorted in sorted(by_min.items()):
            base = ref.get(minute)
            if not base:
                continue
            for s in group_sorted:
                for field, refval in (("cs", base["cs_mean"]), ("gpm", base["gpm_mean"])):
                    if refval is None:
                        continue
                    actual = getattr(s, field)
                    if actual is None:
                        continue
                    if refval == 0:
                        continue
                    pct = (actual - refval) / refval
                    if abs(pct) >= self.tolerance:
                        direction = "higher" if pct > 0 else "lower"
                        d = Deviation(
                            t_min=s.t_min,
                            field=field,
                            actual=actual,
                            reference=round(float(refval), 1),
                            direction=direction,
                            outcome=self.judger.judge(match_result, field, direction),
                            note=self._note(field, direction, s, base),
                        )
                        report.deviations.append(d)

        report.summary = self._summary(report, ref)
        return report

    # -- helpers --
    def _note(self, field, direction, s, base):
        if field == "cs" and direction == "lower":
            return f"补刀滞后：本局{base['n_samples']}盘参考均值"
        if field == "cs":
            return f"补刀领先参考"
        if field == "gpm" and direction == "lower":
            return f"经济发育偏慢"
        return ""

    def _summary(self, report: DiffReport, ref: dict) -> str:
        if report.skipped:
            return report.skip_reason
        if not report.deviations:
            return f"{report.hero}/{report.position} 前N分钟行为与参考基本一致，无显著偏差。"
        good, bad = report.good_count, report.bad_count
        return (
            f"发现 {len(report.deviations)} 处偏差：好 {good} 处，坏 {bad} 处。"
            + ("建议重点复盘坏偏差对应的时间点。" if bad else "整体表现不错，维持参考打法。")
        )
