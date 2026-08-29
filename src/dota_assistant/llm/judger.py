"""LLM 好坏判定（需求 3 增强，可选）。

把 diff 出的偏差列表一次性发给 LLM，让它判断每个偏差导致了好的还是坏的结果，
并给出人话解释。未配置 DOTA_LLM_API_KEY 或调用失败时，自动保留规则判定的
outcome（不覆盖），保证离线可用。
支持环境变量 DOTA_LLM_MAX_TOKENS(默认1000)、DOTA_LLM_REASONING_EFFORT(默认不设/模型默认)。
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import requests

from dota_assistant.core.models import Deviation
from dota_assistant.llm.strategy import OPENROUTER_URL, DEFAULT_MODEL

JUDGE_SYSTEM_PROMPT = """你是资深 Dota 2 教练。下面是一局比赛里，某玩家的行为与职业参考数据库对比出来的
若干偏差项（字段 = 指标，实际 vs 参考，方向）。请逐条判断：这个偏差导致了好结果还是坏结果，
并用一句中文解释为什么（结合 Dota 常识：补刀/经济领先通常是好，死亡偏高通常是坏，但要结合
时间段和位置判断，比如前期劣势路的低经济可能是正常的）。

只输出 JSON 数组，不要任何其他文字，格式：
[{"index": 0, "outcome": "good|bad|neutral", "note": "一句话解释"}, ...]
其中 index 对应输入列表的序号；outcome 只能是 good/bad/neutral 之一。"""


def _llm_key() -> Optional[str]:
    return os.environ.get("DOTA_LLM_API_KEY")


def enrich_with_llm(
    deviations: list[Deviation],
    hero: str,
    position: str,
    match_result: Optional[str] = None,
) -> bool:
    """用 LLM 覆盖每条 Deviation 的 outcome/note。返回是否成功启用了 LLM。"""
    if not deviations:
        return False
    if not _llm_key():
        return False

    url = (os.environ.get("DOTA_LLM_BASE_URL") or OPENROUTER_URL).rstrip("/") + "/chat/completions"
    model = os.environ.get("DOTA_LLM_MODEL") or DEFAULT_MODEL
    headers = {
        "Authorization": f"Bearer {_llm_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/huxingyu881225-netizen/dota2-planner",
    }

    items = [
        {
            "index": i,
            "t_min": d.t_min,
            "field": d.field,
            "actual": d.actual,
            "reference": d.reference,
            "direction": d.direction,
            "rule_outcome": d.outcome,
        }
        for i, d in enumerate(deviations)
    ]
    user = (
        f"英雄:{hero} 位置:{position} 最终结果:{match_result or '未知'}\n"
        f"偏差列表: {json.dumps(items, ensure_ascii=False)}\n"
        "判断结果:"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": int(os.environ.get("DOTA_LLM_MAX_TOKENS", "1000")),
    }
    reasoning_effort = os.environ.get("DOTA_LLM_REASONING_EFFORT")
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=int(os.environ.get("DOTA_LLM_TIMEOUT", "30")),
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"] or "[]"
        # 兼容可能包裹 ```json ... ``` 的输出
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        for entry in parsed:
            idx = entry.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(deviations)):
                continue
            outcome = entry.get("outcome")
            if outcome in ("good", "bad", "neutral"):
                deviations[idx].outcome = outcome
            note = entry.get("note")
            if note:
                deviations[idx].note = note
        return True
    except Exception:  # noqa: 失败保留规则判定
        return False
