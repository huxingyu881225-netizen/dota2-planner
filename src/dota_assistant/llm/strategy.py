"""LLM 策略生成模块。

把一段游戏窗口（如 30 秒）内该英雄/位置的结构化指标，生成一句「核心策略」
文本并落库。走 OpenAI 兼容协议（默认 OpenRouter），未配置 API key 时回退到
本地的模板生成（behavior.build），保证完全离线也能跑。

环境变量：
    DOTA_LLM_API_KEY      —— 配置后才启用 LLM（OpenRouter 等）
    DOTA_LLM_BASE_URL     —— 默认 https://openrouter.ai/api/v1（兼容 OpenAI 协议）
    DOTA_LLM_MODEL        —— 默认 openrouter/auto（或指定如 openai/gpt-4o-mini）
    DOTA_LLM_CONCURRENCY  —— 批量并发数，默认 4
    DOTA_LLM_MAX_TOKENS   —— 单窗口生成最大 token，默认 500（过小如 120 会导致
                             部分模型只输出 reasoning、content 为空）
    DOTA_LLM_REASONING_EFFORT —— 推理强度，默认 high（OpenAI 兼容的 reasoning 模型用）
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import requests

from dota_assistant.core.behavior import build as build_template

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/auto"

SYSTEM_PROMPT = """你是资深 Dota 2 教练。给你一名玩家在某个游戏时间段内的结构化比赛数据，
请用一句（最多两句）中文概括他在这个时间段里的【核心策略】——不是流水账地复述数据，
而是提炼他的意图：他此刻在按什么思路打（对线压制/稳健发育/主动游走/控图/推塔/保人/买眼控视野/
围绕某个关键节奏点等），以及这个策略服务于什么目的。

要求：
- 直接输出策略文本，不要任何解释、前缀或 Markdown。
- 基于数据推断，数据不足就写"稳健发育/待机"，不要编造。
- 语气像职业教练给选手的指令，简短、可执行。"""


def strategy_prompt(hero: str, position: str, window: dict[str, Any]) -> str:
    """单窗口 prompt（供批量组装）。"""
    return (
        f"英雄:{hero} 位置:{position} 时间段:{window.get('t_min', '?')}分钟 "
        f"({window.get('t_sec', 0)}s 起, 窗口{window.get('window_interval', 30)}s)\n"
        f"数据: {json.dumps({k: v for k, v in window.items() if k not in ('t_sec', 't_min', 'window_interval')}, ensure_ascii=False)}\n"
        "核心策略:"
    )


def generate_strategy_batch(
    items: list[dict[str, Any]],
    hero: str,
    position: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> list[str]:
    """为一批窗口生成策略。返回与 items 等长的策略文本列表。

    未配置 api_key 时回退模板（不联网）。
    请求失败时对失败项回退模板，不阻断整个流程。
    """
    key = api_key or os.environ.get("DOTA_LLM_API_KEY")
    if not key:
        return [_template(item, position) for item in items]

    url = (base_url or os.environ.get("DOTA_LLM_BASE_URL") or OPENROUTER_URL).rstrip("/") + "/chat/completions"
    model_name = model or os.environ.get("DOTA_LLM_MODEL") or DEFAULT_MODEL
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/huxingyu881225-netizen/dota2-planner",
    }

    out: list[str] = []
    for item in items:
        try:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": strategy_prompt(hero, position, item)},
                ],
                "temperature": 0.4,
                "max_tokens": int(os.environ.get("DOTA_LLM_MAX_TOKENS", "500")),
            }
            reasoning_effort = os.environ.get("DOTA_LLM_REASONING_EFFORT")
            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort
            resp = requests.post(url, json=payload, headers=headers, timeout=int(os.environ.get("DOTA_LLM_TIMEOUT", "30")))
            resp.raise_for_status()
            text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
            out.append(text if text else _template(item, position))
        except Exception:  # noqa: 任一窗口失败，回退模板，保证灌库不中断
            out.append(_template(item, position))
    return out


def _template(item: dict[str, Any], position: str) -> str:
    return build_template(item, position)
