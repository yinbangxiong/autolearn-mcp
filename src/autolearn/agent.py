# AI_GENERATE_START --
# -*- coding: utf-8 -*-
"""Agent 核心（CLI 直连模式）：感知 → LLM 决策 → 动作执行 → 记录，循环直到 done/fail。

推荐使用 MCP 模式（mcp_server.py）由 AI 助手当大脑；本模块用于无助手时的独立运行。
"""

import json
import re

from openai import OpenAI

from autolearn.config import (
    CAPTURE_SCREENSHOTS,
    HISTORY_STEPS,
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_MODEL,
    MAX_STEPS,
)
from autolearn.executor import execute_action
from autolearn.perceive import find_element, format_state, perceive

SYSTEM_PROMPT = """你是一个 Web 系统自主探索 Agent，负责在网页系统中自主操作，完成用户交给的探索任务。

每一步你会收到：当前页面状态（URL、标题、可交互元素列表，格式 [编号] 标签 "名称"）和最近几步操作历史。

你需要输出一个 JSON 决定下一步动作。可用动作：
- click: 点击元素，参数 {"idx": 编号}
- type: 向输入框填入文本（先清空再填），参数 {"idx": 编号, "text": "内容", "press_enter": false}
- select: 下拉框选择，参数 {"idx": 编号, "value": "选项文本或值"}
- scroll: 页面滚动，参数 {"direction": "down" 或 "up"}
- back: 浏览器后退
- done: 任务完成，参数 {"summary": "总结探索到的内容与路径"}
- fail: 任务无法继续，参数 {"reason": "原因"}

要求：
1. 只输出 JSON，不要输出其他文字，格式：{"thought": "一句话思考", "action": "动作名", "params": {}}
2. 点击菜单/链接前先看清名称，优先探索尚未去过的入口
3. 同一元素连续操作两次页面无变化时，换路径或用 back/scroll
4. 不要猜测页面上不存在的元素编号
"""


def _call_llm(client: OpenAI, prompt: str) -> dict:
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group())


def _hint(element: dict | None, params: dict) -> str:
    if element:
        return f"[{element['idx']}]\"{element.get('name', '')}\""
    if params.get("idx") is not None:
        return f"[{params.get('idx')}]"
    return ""


async def run_agent(page, context, goal: str, recorder):
    """主循环。返回 (是否完成, 总结/原因)。"""
    client = OpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)
    history = []
    for step in range(1, MAX_STEPS + 1):
        try:
            state = await perceive(page)
        except Exception as e:
            return False, f"感知页面失败: {str(e)[:120]}"

        shot = recorder.screenshot(page, step) if CAPTURE_SCREENSHOTS else None
        history_text = "\n".join(history[-HISTORY_STEPS:]) or "（无）"
        prompt = (
            f"探索目标：{goal}\n\n"
            f"已执行步骤：\n{history_text}\n\n"
            f"当前页面状态：\n{format_state(state)}\n\n"
            "请输出下一步 JSON："
        )
        decision = _call_llm(client, prompt)
        action = str(decision.get("action", "")).lower()
        params = decision.get("params") or {}
        element = find_element(state, params.get("idx"))

        ok, result_msg, page = await execute_action(page, context, action, params)

        recorder.record(
            "step",
            step=step,
            url=state["url"],
            title=state["title"],
            thought=decision.get("thought", ""),
            action=action,
            params=params,
            element=element,
            ok=ok,
            result=result_msg,
            screenshot=shot,
        )
        history.append(f"步骤{step} {action}{_hint(element, params)} → {result_msg}")
        print(f"[step {step}] {action}{_hint(element, params)} → {result_msg}")

        if action == "done":
            return True, str(params.get("summary", ""))
        if action == "fail":
            return False, str(params.get("reason", ""))
    return False, f"已达最大步数 {MAX_STEPS}，探索停止"
# AI_GENERATE_END --

