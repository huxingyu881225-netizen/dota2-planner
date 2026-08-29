"""核心抽取：从 gem-dota 解析出的 ParsedPlayer 对象，按前 N 分钟、每 M 秒取样。

gem 秒级序列（parallel arrays，采样约 1 次/秒，times[i] = tick 数，30 刻=1 秒）：
    times, gold_t, total_earned_gold_t, net_worth_t, lh_t, dn_t, xp_t
事件：
    kills_log / purchase_log     -> CombatLogEntry（有 .tick，购买项在 value_name）
    obs_log / sen_log            -> WardEvent（有 .tick）
    位置                          -> position_log: [(tick, x, y), ...]
标量：kills / deaths / assists（服务器计分板）

重要：gem-dota 返回的 tick 是 **replay 的绝对 tick**（从录像文件开始计），不是游戏从 0 秒开始的
tick。因此所有 tick 换算游戏秒都用 `(tick - base_tick) / 30`，base_tick = match.game_start_tick。
若拿不到 game_start_tick（None/0），退化为原文行为（直接 /30）。
"""
from __future__ import annotations

from typing import Any

from dota_assistant.core.behavior import build as build_behavior
from dota_assistant.core.models import Sample

TICKS_PER_SECOND = 30


def _resolve_base_tick(data: dict[str, Any]) -> int:
    """从 data['match'] 取 game_start_tick，作为游戏 0 秒的基准 tick。"""
    match = data.get("match")
    if match is None:
        return 0
    gt = getattr(match, "game_start_tick", None)
    try:
        return int(gt) if gt else 0
    except (TypeError, ValueError):
        return 0


def _to_sec(tick, base_tick: int = 0) -> int:
    """绝对 tick -> 游戏内秒：(tick - base_tick) / 30。"""
    if tick is None:
        return 0
    abs_tick = int(tick)
    game_tick = abs_tick - (base_tick or 0)
    return int(round(game_tick / TICKS_PER_SECOND))


def _to_series(times, vals, base_tick: int = 0) -> list[tuple[int, float]]:
    """把 (tick, value) 对齐到 (游戏秒, value)，按秒升序。"""
    out = []
    for i in range(min(len(times), len(vals))):
        t, v = times[i], vals[i]
        if v is None:
            continue
        sec = _to_sec(t, base_tick)
        out.append((sec, float(v)))
    out.sort(key=lambda x: x[0])
    return out


def _at(pairs: list[tuple[int, float]], t_sec: int) -> Any:
    """取 <= t_sec 的最近值；无则 None。"""
    best = None
    for sec, v in pairs:
        if sec <= t_sec:
            best = v
        else:
            break
    return best


def _series(player, base_tick: int = 0) -> dict[str, list[tuple[int, float]]]:
    times = list(getattr(player, "times", None) or [])
    return {
        "lh": _to_series(times, getattr(player, "lh_t", None), base_tick),
        "nw": _to_series(times, getattr(player, "net_worth_t", None), base_tick),
        "gold": _to_series(times, getattr(player, "gold_t", None), base_tick),
        "earned": _to_series(times, getattr(player, "total_earned_gold_t", None), base_tick),
        "xp": _to_series(times, getattr(player, "xp_t", None), base_tick),
        "dn": _to_series(times, getattr(player, "dn_t", None), base_tick),
    }


def _log_tick_seconds(log, lower_sec: int, upper_sec: int, base_tick: int = 0) -> int:
    """在 (lower, upper] 游戏秒区间内，命中日志的事件数。"""
    cnt = 0
    for e in (log or []):
        tick = getattr(e, "tick", None)
        sec = _to_sec(tick, base_tick) if tick is not None else None
        if sec is None:
            continue
        if lower_sec < sec <= upper_sec:
            cnt += 1
    return cnt


def _items_in_window(purchase_log, lower_sec: int, upper_sec: int, base_tick: int = 0) -> list[str]:
    items = []
    for e in (purchase_log or []):
        tick = getattr(e, "tick", None)
        if tick is None:
            continue
        sec = _to_sec(tick, base_tick)
        name = getattr(e, "value_name", None) or getattr(e, "key", None) or getattr(e, "value", None) or ""
        if lower_sec < sec <= upper_sec and name:
            items.append(str(name).replace("item_", "").replace("_", " "))
    return items


def _count_ward(log, t_sec: int, base_tick: int = 0) -> int:
    """统计 WardEvent（obs_log/sen_log）中 <= t_sec 游戏秒的插眼数。"""
    cnt = 0
    for e in (log or []):
        tick = getattr(e, "tick", None)
        if tick is None:
            continue
        if _to_sec(tick, base_tick) <= t_sec:
            cnt += 1
    return cnt


def _position_at(position_log, t_sec: int, base_tick: int = 0):
    best = (None, None)
    for tick, x, y in position_log:
        if _to_sec(tick, base_tick) <= t_sec:
            best = (float(x), float(y))
        else:
            break
    return best



def _minute_series_value(player, attr: str, minute: int) -> Any:
    """从分钟级序列(如 total_deaths_t_min/min_idx)取第 minute 分钟的累计值。若越界则取最后一个。"""
    vals = getattr(player, attr, None) or []
    if not vals:
        return None
    idx = min(int(minute), len(vals) - 1)
    try:
        return vals[idx]
    except Exception:
        return None

def _int(v) -> Any:
    if v is None:
        return None
    try:
        return int(round(v))
    except (TypeError, ValueError):
        return None


def extract_windows(
    data: dict[str, Any],
    minute_n: int,
    interval_m: int,
) -> list[dict[str, Any]]:
    """按前 N 分钟、每 M 秒，输出每个窗口的结构化指标字典。

    每个窗口的 key：t_sec, t_min, window_interval, cs, gpm(=earned*60/t), xpm(=xp/(t/60)), networth,
    gold, xp, dn, window_gain, kills_total, deaths, assists, kills_in_window,
    obs_bought, sen_bought, items_bought[]（可选）, pos_x/pos_y（可选）。
    供 LLM 生成「核心策略」文本。
    """
    player = data.get("player")
    if player is None:
        return []

    base_tick = _resolve_base_tick(data)
    tmax = minute_n * 60
    series = _series(player, base_tick)
    kills_log = list(getattr(player, "kills_log", None) or [])
    obs_log = list(getattr(player, "obs_log", None) or [])
    sen_log = list(getattr(player, "sen_log", None) or [])
    purchase_log = list(getattr(player, "purchase_log", None) or [])
    position_log = list(getattr(player, "position_log", None) or [])
    assists = int(getattr(player, "assists", 0) or 0)

    windows: list[dict[str, Any]] = []
    t = 0
    while t <= tmax:
        # 累计值（累计赚取金 / 累计经验）——用于算 GPM/XPM 与窗口收入增量
        cur_earned = _at(series["earned"], t)
        prev_earned = _at(series["earned"], max(0, t - interval_m))
        cur_gold = _at(series["gold"], t)
        cur_xp = _at(series["xp"], t)

        # window_gain：累计收入 total_earned_gold_t 的窗口差值（买装备不消耗累计收入，故不会因买东西下降）
        window_gain = 0.0
        if cur_earned is not None and prev_earned is not None:
            window_gain = cur_earned - prev_earned

        # GPM = 累计赚取金 * 60 / t_sec（t_sec=0 -> 0）；XPM = xp / (t_sec/60)
        if t > 0:
            gpm = (cur_earned * 60.0 / t) if cur_earned is not None else None
            xpm = (cur_xp / (t / 60.0)) if cur_xp is not None else None
        else:
            gpm = 0.0
            xpm = 0.0

        # deaths：用分钟级累计死亡序列按当前分钟取，不写整局最终值
        minute_idx = int(t // 60)
        cum_deaths = _minute_series_value(player, "total_deaths_t_min", minute_idx)
        if cum_deaths is None:
            cum_deaths = 0

        metrics: dict[str, Any] = {
            "t_sec": t,
            "t_min": round(t / 60.0, 2),
            "window_interval": interval_m,
            "cs": _int(_at(series["lh"], t)),
            "gpm": _int(gpm),
            "networth": _int(_at(series["nw"], t)),
            "gold": _int(cur_gold),
            "xp": _int(cur_xp),
            "xpm": _int(xpm),
            "dn": _int(_at(series["dn"], t)),
            "window_gain": _int(window_gain),
            "kills_total": int(getattr(player, "kills", 0) or 0),
            "deaths": int(cum_deaths),
            "assists": assists,
            "deaths_cum_at_min": int(cum_deaths),
            "kills_in_window": _log_tick_seconds(kills_log, t - interval_m, t, base_tick),
            "obs_bought": _count_ward(obs_log, t, base_tick),
            "sen_bought": _count_ward(sen_log, t, base_tick),
        }
        new_items = _items_in_window(purchase_log, t - interval_m, t, base_tick)
        if new_items:
            metrics["items_bought"] = new_items[:4]
        pos_x, pos_y = _position_at(position_log, t, base_tick)
        if pos_x is not None:
            metrics["pos_x"], metrics["pos_y"] = pos_x, pos_y
        windows.append(metrics)
        t += interval_m
    return windows


def extract(
    data: dict[str, Any],
    hero: str,
    position: str,
    minute_n: int,
    interval_m: int,
) -> list[Sample]:
    """采样前 N 分钟、每 M 秒的玩家行为（behavior 用模板生成，供无 LLM 或 diff 场景用）。

    有 LLM 时，ingester 会改用 extract_windows 的指标交给 LLM 生成策略文本。
    """
    samples: list[Sample] = []
    for metrics in extract_windows(data, minute_n, interval_m):
        behavior = build_behavior(metrics, position)
        pos_x = metrics.get("pos_x")
        pos_y = metrics.get("pos_y")
        samples.append(
            Sample(
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
                pos_x=pos_x,
                pos_y=pos_y,
                extra=metrics,
            )
        )
    return samples
