# AI_GENERATE_START -
# -*- coding: utf-8 -*-
"""技能回放引擎：按程序记忆的步骤自动执行并逐步自愈。

自愈策略：
- 需要编号的步骤先按 name_hint 在最新感知里模糊匹配元素（对编号漂移免疫）；
- click/click_text 失败时回退到"感知 → 名称匹配 → 按编号点击"再试一次；
- 单步失败即中止并返回现场，由大脑决定是否重新探索并更新技能。

步骤可选校验字段：
- expect_text: 执行后页面上应出现该文本（元素名包含即可）
- expect_url_contains: 执行后 URL 应包含该子串
"""

from autolearn.executor import execute_action
from autolearn.perceive import find_element, perceive


def _fill(template: str, params: dict) -> str:
    """把 {{param}} / <param> 占位符替换为实际参数；未知占位符原样保留。"""
    out = template
    for k, v in (params or {}).items():
        out = out.replace("{{" + k + "}}", str(v))
        out = out.replace("<" + k + ">", str(v))
    return out


async def _resolve_by_name(page, hint: str, params: dict):
    """按名称线索在最新页面状态中解析元素，返回 (params, element)。"""
    state = await perceive(page)
    el = None
    if hint:
        el = next((e for e in state["elements"] if hint in (e.get("name") or "")), None)
    if el is None and params.get("idx") is not None:
        el = find_element(state, params.get("idx"))
    if el is not None:
        params = dict(params)
        params["idx"] = el["idx"]
    return params, el


def _frame_for(page, element):
    """元素在 iframe 内时返回对应 Frame，否则 None。"""
    if element is not None and element.get("frame") not in (None, 0):
        frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
        if element["frame"] < len(frames):
            return frames[element["frame"]]
    return None


async def replay_skill(page, context, skill: dict, params: dict, recorder, shot_fn=None):
    """回放技能。返回 (是否全部成功, 报告文本, 最终 page)。"""
    results = []
    all_ok = True
    steps = skill.get("steps", [])
    for i, raw_step in enumerate(steps, 1):
        step = {k: (_fill(str(v), params) if isinstance(v, str) else v) for k, v in raw_step.items()}
        action = str(step.get("action", "")).lower()
        step_params = {k: v for k, v in step.items() if k not in ("action", "note", "name_hint", "expect_text", "expect_url_contains")}
        element = None
        if action == "click" or "idx" in step_params:
            hint = str(step.get("name_hint") or step.get("expect_name") or "")
            try:
                step_params, element = await _resolve_by_name(page, hint, step_params)
            except Exception as e:
                results.append(f"{i}) {action}: 解析元素失败 {str(e)[:80]}")
                all_ok = False
                break

        ok, msg, page = await execute_action(page, context, action, step_params, _frame_for(page, element))

        if not ok and action in ("click", "click_text"):
            # 自愈：重新感知，按文本/名称线索找到元素后用编号精确点击
            heal_hint = str(step.get("text") or step.get("name_hint") or step.get("expect_name") or "")
            try:
                hp, el2 = await _resolve_by_name(page, heal_hint, {"idx": None})
                if el2 is not None:
                    ok, msg, page = await execute_action(page, context, "click", {"idx": el2["idx"]}, _frame_for(page, el2))
                    if ok:
                        msg += "（自愈成功）"
            except Exception:
                pass

        verify_note = ""
        expect_url = str(step.get("expect_url_contains") or "")
        if ok and expect_url and expect_url not in page.url:
            ok = False
            verify_note = f"（校验失败：URL 应含「{expect_url}」，实际 {page.url[:80]}）"
        expect_text = str(step.get("expect_text") or "")
        if ok and expect_text:
            try:
                st = await perceive(page)
                if not any(expect_text in (e.get("name") or "") for e in st["elements"]):
                    ok = False
                    verify_note = f"（校验失败：页面上未出现「{expect_text}」）"
            except Exception:
                pass

        if recorder is not None:
            recorder.record(
                "skill_step",
                skill=skill.get("id"),
                step_index=i,
                action=action,
                params=step_params,
                ok=ok,
                result=msg + verify_note,
            )
        results.append(f"{i}) {action}: {msg}{verify_note}")
        if not ok:
            all_ok = False
            break

    return all_ok, f"技能「{skill.get('name')}」回放{'成功' if all_ok else '中断'}: " + "；".join(results), page
# AI_GENERATE_END -

