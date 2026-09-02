"""LLM 策略生成模块。

把一段游戏窗口（如 30 秒）内该英雄/位置的结构化指标，生成一句「核心策略」
文本并落库。走 OpenAI 兼容协议（默认 OpenRouter），未配置 API key 时回退到
本地的模板生成（behavior.build），保证完全离线也能跑。

环境变量：
    DOTA_LLM_API_KEY      —— 配置后才启用 LLM（OpenRouter 等）
    DOTA_LLM_BASE_URL     —— 默认 https://openrouter.ai/api/v1（兼容 OpenAI 协议）
    DOTA_LLM_MODEL        —— 默认 openrouter/auto（或指定如 openai/gpt-4o-mini）
    DOTA_LLM_CONCURRENCY  —— 批量并发数，默认 4
    DOTA_LLM_MAX_TOKENS   —— 单窗口生成最大 token，默认 1000（过小如 120 会导致
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

SYSTEM_PROMPT = """你是资深 Dota 2 教练。给你一名玩家在某局职业比赛里的一个时间窗口的
定性参考信号（经济水平/装备/视野/位置等），你要输出一条【advice】：只包含可执行、可迁移的
通用指令，供玩家在自己对局中照着做。

advice 必须包含（可合并到一两句内）：
1. 装备/补给/视野建议：基于已有装备推断下一步补什么（给出具体装备名）。
2. 战术指令：攻击谁/游走或支援哪条路/控哪个目标（如压制对方核心、去中路帮推、控盾/控视野等）。

严禁：
- 严禁复述这局例子的原始状态/数据。禁止出现："本局9杀1死"、"你刚买了X"、"当前经济XXX"、
  "现在多少补刀"、"第X分钟你击杀了谁" 这类描述例子战况的话。
- 不要输出标题、解释、Markdown，不要"核心策略："等前缀。
- 不要背起始装清单；可以用起始装/已有装备**推断**该补什么，但输出只留结论（"补魔棒"）。

约束：
1. 一到三句中文，简短可执行，职业教练指令口吻。
2. 必须至少包含一个具体动作：具体装备（魔棒、草鞋、风灵之纹、凝魂之泪、诡计之雾、岗哨守卫、
   侦查守卫、回城卷轴、血腥榴弹、先灵火、树之祭祀等）或 具体战术（压制/支援/推塔/控图/买眼地点）。
3. 若参考信号给了 starting_items（开局装备），前 1 分钟的 advice 应基于它判断开局该补什么续航/补给。
4. 数据不足时战术可写"稳健发育/待机"，但装备建议仍要给出保守选项（买眼/带TP/带雾）。
5. 位置措辞准确：offlane_support 统一说"劣势路辅助/四号位"，其搭档说"三号位/劣势路核心"；
   其余照常：carry=一号位/优势路核心，mid=二号位/中路核心，offline=三号位/劣势路核心，
   safelane_support=五号位/优势路辅助。"""


POSITION_CN = {
    "carry": "一号位/优势路核心",
    "mid": "二号位/中路核心",
    "offline": "三号位/劣势路核心",
    "offlane_support": "劣势路辅助/四号位",
    "safelane_support": "五号位/优势路辅助",
}


def _action_signal(window: dict[str, Any]) -> dict[str, Any]:
    """把窗口指标转成「行动信号」（去掉原始数字，只留可推断的定性信息）。

    目的：避免 LLM 复述例子录像的状态（如"9杀1死""当前经济"），只给判断
    "补什么/去哪/攻击谁"所需的定性信号。
    """
    sig: dict[str, Any] = {}

    # 经济水平（定性）
    gpm = window.get("gpm")
    if isinstance(gpm, (int, float)):
        if gpm >= 600:
            sig["经济水平"] = "高"
        elif gpm >= 450:
            sig["经济水平"] = "中"
        else:
            sig["经济水平"] = "低"

    # 装备（仅列名字，不评价）
    if window.get("starting_items"):
        sig["起始装"] = window["starting_items"]
    if window.get("items_bought_so_far"):
        sig["已有装备"] = window["items_bought_so_far"]
    if window.get("items_bought_in_window"):
        sig["本窗口新增"] = window["items_bought_in_window"]

    # 视野（定性）
    if window.get("obs_bought") or window.get("sen_bought"):
        sig["视野"] = "有插眼动作"

    # 位置坐标（若给出，供"去哪路"判断）
    if window.get("pos_x") is not None and window.get("pos_y") is not None:
        sig["地图位置"] = [round(float(window["pos_x"]), 0), round(float(window["pos_y"]), 0)]

    return sig


def strategy_prompt(hero: str, position: str, window: dict[str, Any]) -> str:
    """单窗口 prompt（供批量组装）。只给定性行动信号，不给原始战况数字。"""
    pos_cn = POSITION_CN.get(position, position)
    signal = _action_signal(window)
    return (
        f"英雄:{hero} 位置:{position}({pos_cn}) 时间段:{window.get('t_min', '?')}分钟 "
        f"({window.get('t_sec', 0)}s 起, 窗口{window.get('window_interval', 30)}s)\n"
        f"参考信号: {json.dumps(signal, ensure_ascii=False)}\n"
        "advice:"
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
                "max_tokens": int(os.environ.get("DOTA_LLM_MAX_TOKENS", "1000")),
            }
            # 默认 high（用户要求）；可用 DOTA_LLM_REASONING_EFFORT 覆盖 (low/medium/high)
            reasoning_effort = os.environ.get("DOTA_LLM_REASONING_EFFORT", "high")
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
