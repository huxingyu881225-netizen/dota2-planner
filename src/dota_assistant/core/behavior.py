"""Behavior narration builder.

Turns raw metrics + events at a sampling point into a short human-readable
"main behavior" sentence, and (optionally) into an action tag used by the diff
engine.
"""
from __future__ import annotations

from typing import Any

ACTION_CN = {
    "laning": "对线",
    "farming": "发育/刷钱",
    "ganking": "游走抓人",
    "teamfight": "团战/支援",
    "pushing": "推塔/推进",
    "warding": "视野控制",
    "roshan": "控盾(Rosh)",
    "roaming": "控图/游走",
    "idle": "待命/占位",
}


def infer_action_key(metrics: dict[str, Any]) -> str:
    """Pick an action tag from metrics. Order matters: concrete wins."""
    if metrics.get("action"):
        return str(metrics["action"])
    if metrics.get("event") in ("roshan", "aegis"):
        return "roshan"
    if metrics.get("event") in ("tower_damage", "tower") or metrics.get("tower_damage", 0) > 0:
        return "pushing"
    if metrics.get("obs_bought", 0) or metrics.get("sen_bought", 0):
        return "warding"
    if metrics.get("kills_in_window", 0) > 0 or metrics.get("assists_in_window", 0) > 0:
        return "teamfight"
    if metrics.get("jungled"):
        return "farming"
    if metrics.get("roaming"):
        return "roaming"
    return "laning"


def build(metrics: dict[str, Any], _position: str) -> str:
    """Compose a readable behavior line from a Sample's metric dict.

    Expected keys (all optional): t_sec, cs, gpm, networth, kills, deaths,
    items_bought[], obs_bought, sen_bought, event, plus anything the extractor
    puts into `extra`.
    """
    t = int(metrics.get("t_sec", 0) or 0)
    stamp = f"{t // 60:02d}:{t % 60:02d}"

    action = ACTION_CN.get(infer_action_key(metrics), "对线")
    parts = [f"{stamp} {action}"]

    if cs := metrics.get("cs"):
        parts.append(f"CS {cs}")
    if gpm := metrics.get("gpm"):
        parts.append(f"GPM {gpm}")
    if nw := metrics.get("networth"):
        parts.append(f"净财富 {nw}")
    if k := metrics.get("kills", 0):
        parts.append(f"K {k}")
    if d := metrics.get("deaths", 0):
        parts.append(f"D {d}")

    # 起始装：前 1 分钟逐项列出
    starting = metrics.get("starting_items") or []
    if starting:
        parts.append("起始装:" + ",".join(str(i) for i in starting))
    # 本窗口新增购买
    in_window = metrics.get("items_bought_in_window") or metrics.get("items_bought") or []
    if in_window:
        parts.append("本窗口新增购买:" + ",".join(str(i) for i in in_window))
    # 累计已购
    so_far = metrics.get("items_bought_so_far") or []
    if so_far:
        parts.append("已购:" + ",".join(str(i) for i in so_far))

    obs = int(metrics.get("obs_bought", 0) or 0)
    sen = int(metrics.get("sen_bought", 0) or 0)
    if obs or sen:
        bits = []
        if obs:
            bits.append(f"假眼x{obs}")
        if sen:
            bits.append(f"真眼x{sen}")
        parts.append("".join(bits))

    if ev := metrics.get("event"):
        parts.append(f"事件:{ev}")

    return "；".join(parts)
