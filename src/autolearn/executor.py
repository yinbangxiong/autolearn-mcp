# AI_GENERATE_START ---
# -*- coding: utf-8 -*-
"""动作执行层：把 AI 助手/LLM 决定的动作落到浏览器上（async，CLI 与 MCP 共用）。

元素类动作（click/type/select/click_text）支持在 iframe 内执行：传入 frame（Playwright Frame 对象）；
页面级动作（scroll/back）始终作用于 page。click_text 按精确文本定位，主框架找不到时遍历 iframe。
"""


async def _click_by_text(page, text: str):
    """按精确文本点击元素；主框架找不到时遍历 iframe。返回 (是否成功, 结果说明)。"""
    try:
        await page.locator(f'text="{text}"').first.click(timeout=5000)
        return True, "成功"
    except Exception:
        pass
    for fr in page.frames:
        if fr is page.main_frame:
            continue
        try:
            await fr.locator(f'text="{text}"').first.click(timeout=3000)
            return True, "成功"
        except Exception:
            continue
    return False, f"未找到文本为「{text}」的可点击元素"


async def execute_action(page, context, action: str, params: dict, frame=None):
    """执行动作，返回 (是否成功, 结果说明, 当前应使用的 page)。"""
    idx = params.get("idx")
    scope = frame if frame is not None else page
    try:
        if action == "click":
            await scope.locator(f'[data-al-id="{int(idx)}"]').click(timeout=8000)
        elif action == "click_text":
            text = str(params.get("text", "")).strip()
            if not text:
                return False, "click_text 缺少 text 参数", page
            ok2, msg2 = await _click_by_text(page, text)
            if not ok2:
                return False, msg2, page
        elif action == "type":
            loc = scope.locator(f'[data-al-id="{int(idx)}"]')
            await loc.fill(str(params.get("text", "")), timeout=8000)
            if params.get("press_enter"):
                await loc.press("Enter")
        elif action == "select":
            loc = scope.locator(f'[data-al-id="{int(idx)}"]')
            try:
                await loc.select_option(label=str(params.get("value", "")), timeout=8000)
            except Exception:
                await loc.select_option(str(params.get("value", "")), timeout=8000)
        elif action == "scroll":
            await page.mouse.wheel(0, 800 if params.get("direction", "down") == "down" else -800)
        elif action == "back":
            await page.go_back()
        elif action in ("done", "fail"):
            return True, "会话结束", page
        else:
            return False, f"未知动作: {action}", page
    except Exception as e:  # 动作失败也要反馈给调用方，让大脑自行调整
        return False, f"执行失败: {str(e)[:120]}", page

    # 等页面稳定；SPA 轮询导致 networkidle 超时属正常，不视为失败
    try:
        await scope.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass
    await page.wait_for_timeout(300)

    # 点击打开了新标签页时切换过去
    if len(context.pages) > 1 and context.pages[-1] is not page:
        page = context.pages[-1]
        await page.bring_to_front()
    return True, "成功", page
# AI_GENERATE_END ---

