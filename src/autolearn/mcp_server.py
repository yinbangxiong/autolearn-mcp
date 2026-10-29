# AI_GENERATE_START -------
# -*- coding: utf-8 -*-
"""autolearn MCP Server：把浏览器感知/执行/记录暴露为 MCP 工具。

大脑由 AI 助手（Trae / Claude / Codex 等任何支持 MCP 的客户端）担任，
本服务只提供"眼睛"和"手"，并把探索过程沉淀为情景记忆。

工具清单与推荐循环：
1. open_system(url, goal)     打开目标系统（自动创建会话记录；弹窗人工登录）
2. save_login_state()         登录完成后保存登录态，下次免登录
3. perceive_page()            读取当前页面可交互元素（自动截图）
4. act(action_json, thought)  执行一步动作，返回结果 + 最新页面状态
5. finish(summary, status)    结束会话，关闭浏览器，写 session_end
"""

import json

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

from autolearn.config import (
    AUTO_PASSWORD,
    AUTO_USERNAME,
    DATA_DIR,
    HEADLESS,
    TARGET_URL,
)
from autolearn.executor import execute_action
from autolearn.perceive import find_element, format_state, perceive
from autolearn.recorder import SessionRecorder
from autolearn.reflect import (
    build_digest,
    load_skill,
    mark_processed,
    record_skill_verification,
    recall as memory_recall,
    save_semantic,
    save_skill,
)
from autolearn.skill_runner import replay_skill

mcp = FastMCP(
    "autolearn",
    instructions=(
        "系统自动学习工具。循环用法：perceive_page 看页面 → act 执行动作 → "
        "根据返回的最新页面状态继续决策；探索完成调用 finish 总结。"
        "act 的 idx 必须来自最近一次返回的元素列表。"
    ),
)

STATE_FILE = DATA_DIR / "state.json"
_S = {"pw": None, "browser": None, "context": None, "page": None, "recorder": None, "step": 0, "shot_seq": 0}


async def _ensure_browser():
    if _S["browser"] is None:
        _S["pw"] = await async_playwright().start()
        _S["browser"] = await _S["pw"].chromium.launch(headless=HEADLESS)
        storage = str(STATE_FILE) if STATE_FILE.exists() else None
        _S["context"] = await _S["browser"].new_context(
            storage_state=storage,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )


async def _shot(page, name: str):
    """截图到当前会话目录，返回相对路径；失败不阻断。"""
    if _S["recorder"] is None:
        return None
    rel = f"shots/{name}.png"
    try:
        await page.screenshot(path=str(_S["recorder"].dir / rel))
        return rel
    except Exception:
        return None


@mcp.tool()
async def open_system(url: str = "", goal: str = "自由探索系统结构与功能") -> str:
    """打开目标系统并开始一次探索会话。url 为空则用 .env 里的 TARGET_URL。
    浏览器窗口会弹出，可先人工完成登录，再调用 save_login_state()。"""
    await _ensure_browser()
    target = url or TARGET_URL
    if not target:
        return "错误：未提供 url，且 .env 未配置 TARGET_URL"
    if _S["page"] is None:
        _S["page"] = await _S["context"].new_page()
    await _S["page"].goto(target, wait_until="domcontentloaded", timeout=60000)
    if _S["recorder"] is None:
        _S["recorder"] = SessionRecorder(goal)
    _S["step"] = 0
    state = await perceive(_S["page"])
    shot = await _shot(_S["page"], "current_view")
    out = (
        f"已打开: {target}\n会话目录: {_S['recorder'].session_dir}\n"
        f"截图: {shot}\n\n{format_state(state)}"
    )
    if "login" in target.lower() or state["count"] == 0:
        out += "\n\n提示：若停留在登录页，请在浏览器窗口人工登录后调用 save_login_state()。"
    return out


@mcp.tool()
async def save_login_state() -> str:
    """把当前浏览器会话的 Cookie/Storage 保存到 data/state.json，下次启动免登录。"""
    if _S["context"] is None:
        return "错误：请先调用 open_system"
    await _S["context"].storage_state(path=str(STATE_FILE))
    return f"登录态已保存: {STATE_FILE}"


@mcp.tool()
async def perceive_page() -> str:
    """读取当前页面的可交互元素列表（自动截图 current_view.png）。
    元素编号 [n] 即 act 时用的 idx，编号以最近一次 perceive_page/act 返回为准。"""
    if _S["page"] is None:
        return "错误：请先调用 open_system"
    state = await perceive(_S["page"])
    shot = await _shot(_S["page"], "current_view")
    out = format_state(state)
    if shot:
        out += f"\n\n截图: {shot}"
    return out


@mcp.tool()
async def act(action_json: str, thought: str = "", expect_name: str = "") -> str:
    """执行一步或一串浏览器动作，返回执行结果与最新页面状态。

    单动作 action_json 示例：
    {"action":"click","idx":3}
    {"action":"click_text","text":"流水认领"}
    {"action":"type","idx":5,"text":"报销单","press_enter":true}
    {"action":"select","idx":7,"value":"已审核"}
    {"action":"scroll","direction":"down"}
    {"action":"back"}

    链式动作（一次调用内顺序执行，用于"点开下拉→点子项"等需连续操作的场景）：
    {"actions":[{"action":"click","idx":39},{"action":"click_text","text":"流水认领"}]}
    除第一步可用 idx 外，后续步骤建议全部用 click_text 按文本定位（下拉子项感知不到编号）。

    expect_name：第一步动作期望的元素名称关键字，防止编号漂移；对不上时自动按名称重匹配，
    匹配不到则不执行任何动作并返回最新页面状态。idx 必须来自最近一次 perceive_page/act 返回。"""
    if _S["page"] is None:
        return "错误：请先调用 open_system"
    try:
        raw = json.loads(action_json)
    except json.JSONDecodeError:
        return f"错误：action_json 不是合法 JSON: {action_json[:80]}"
    if isinstance(raw, dict) and isinstance(raw.get("actions"), list):
        plan = [p for p in raw["actions"] if isinstance(p, dict)]
    else:
        plan = [raw] if isinstance(raw, dict) else []
    if not plan:
        return "错误：action_json 中没有有效动作"

    page = _S["page"]
    try:
        state_before = await perceive(page)
    except Exception as e:
        return f"感知页面失败: {str(e)[:120]}"

    results = []
    adjusted_note = ""
    for i, sub in enumerate(plan):
        action = str(sub.get("action", "")).lower()
        params = {k: v for k, v in sub.items() if k != "action"}
        element = find_element(state_before, params.get("idx")) if "idx" in params else None

        # 防编号漂移：仅校验第一步
        if i == 0 and expect_name:
            if element is None or expect_name not in (element.get("name") or ""):
                cand = next(
                    (el for el in state_before["elements"] if expect_name in (el.get("name") or "")),
                    None,
                )
                if cand is not None:
                    adjusted_note = f"（编号漂移已自动校正 {params.get('idx')}→{cand['idx']}）"
                    params["idx"] = cand["idx"]
                    element = cand
                else:
                    return (
                        f"错误：页面上找不到名称含「{expect_name}」的元素，未执行任何动作。\n\n"
                        + format_state(state_before)
                    )

        # 元素在 iframe 内时，定位到对应帧执行
        frame = None
        if element is not None and element.get("frame") not in (None, 0):
            frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
            if element["frame"] < len(frames):
                frame = frames[element["frame"]]

        ok, msg, page = await execute_action(page, _S["context"], action, params, frame)
        _S["step"] += 1
        if _S["recorder"] is not None:
            _S["recorder"].record(
                "step",
                step=_S["step"],
                url=state_before["url"],
                title=state_before["title"],
                thought=thought if len(plan) == 1 else f"{thought} [{i + 1}/{len(plan)}]",
                action=action,
                params=params,
                element=element,
                ok=ok,
                result=msg,
                screenshot=None,
            )
        results.append(f"{i + 1}) {action}: {msg}")
        if not ok:
            break

    _S["page"] = page
    _S["shot_seq"] += 1
    shot = await _shot(page, f"step_{_S['shot_seq']:04d}")
    if _S["recorder"] is not None:
        _S["recorder"].record("step_shot", seq=_S["shot_seq"], path=shot, after_step=_S["step"])
    try:
        state_after = await perceive(page)
    except Exception as e:
        return f"执行结果: {'；'.join(results)}{adjusted_note}\n感知新状态失败: {str(e)[:120]}"
    out = f"执行结果: {'；'.join(results)}{adjusted_note}\n\n{format_state(state_after)}"
    if shot:
        out += f"\n\n截图: {shot}"
    return out


@mcp.tool()
async def finish(summary: str = "", status: str = "done") -> str:
    """结束本次探索会话：写入 session_end 并关闭浏览器。status 可选 done/stopped。"""
    mem_path = None
    if _S["recorder"] is not None:
        _S["recorder"].record("session_end", status=status, summary=summary)
        mem_path = str(_S["recorder"].file)
    try:
        if _S["browser"] is not None:
            await _S["browser"].close()
        if _S["pw"] is not None:
            await _S["pw"].stop()
    except Exception:
        pass
    # shot_seq 有意不重置：截图序号全局递增，避免重开会话覆盖历史截图
    _S.update({"pw": None, "browser": None, "context": None, "page": None, "recorder": None, "step": 0})
    return f"会话已结束。情景记忆: {mem_path}"


@mcp.tool()
async def export_memory_digest(max_sessions: int = 5) -> str:
    """导出未消化的探索会话蒸馏摘要（情景记忆 → 大脑）。
    大脑据此总结出页面知识与操作技能，调用 save_semantic_memory / save_skill 沉淀，
    完成后调用 mark_sessions_processed 标记已消化。"""
    digest, names = build_digest(max_sessions)
    header = f"待消化会话 {len(names)} 个: {', '.join(names)}\n\n" if names else ""
    return header + digest


@mcp.tool()
async def save_semantic_memory(title: str, content: str, source: str = "") -> str:
    """把蒸馏出的语义知识（页面结构/业务规则/操作要点）写入语义记忆 semantic.md。
    同名标题节会被整体更新。title 建议形如「平台｜司库系统」或「页面｜AI智报门户」。"""
    path = save_semantic(title, content, source)
    return f"语义记忆已写入: {path}\n节标题: {title}"


@mcp.tool()
async def save_skill(name: str, description: str, steps_json: str, source: str = "") -> str:
    """把蒸馏出的可复用操作技能写入程序记忆。steps_json 示例：
    [{"action":"click_text","text":"配置平台"},
     {"action":"click_text","text":"表单配置"}]
    步骤定位优先用 text（稳定），不要用探索时的临时编号 idx。"""
    try:
        steps = json.loads(steps_json)
        if not isinstance(steps, list):
            raise ValueError("not a list")
    except (json.JSONDecodeError, ValueError) as e:
        return f"错误：steps_json 不是合法的 JSON 数组: {e}"
    path = save_skill(name, description, steps, source)
    return f"技能已保存: {path}"


@mcp.tool()
async def mark_sessions_processed(session_names: str) -> str:
    """把已蒸馏完成的会话标记为已消化（逗号分隔的会话目录名），避免重复导出。"""
    names = [n.strip() for n in session_names.split(",") if n.strip()]
    count = mark_processed(names)
    return f"已标记 {count} 个会话为已消化"


@mcp.tool()
async def recall(query: str = "") -> str:
    """检索沉淀的记忆（语义知识 + 操作技能），任务开始前调用以注入历史经验。
    query 为空返回记忆总览；传关键字（如「配置平台」「报销」「导航」）返回匹配内容。"""
    return memory_recall(query)


@mcp.tool()
async def run_skill(skill_id: str, params_json: str = "{}") -> str:
    """回放程序记忆中的技能（自动执行步骤并逐步自愈与校验）。
    skill_id 支持技能 id 或名称（如「进入平台子模块」）；
    params_json 为技能参数，如 {"platform": "业财融合", "module": "流水认领"}。
    需先 open_system 打开系统。回放成功会累计技能 verified 次数，失败记录 history。"""
    if _S["page"] is None:
        return "错误：请先调用 open_system"
    skill = load_skill(skill_id)
    if skill is None:
        return f"错误：找不到技能「{skill_id}」。\n\n{memory_recall('')}"
    try:
        params = json.loads(params_json) if params_json and params_json.strip() else {}
        if not isinstance(params, dict):
            raise ValueError("params 必须是对象")
    except (json.JSONDecodeError, ValueError) as e:
        return f"错误：params_json 不合法: {e}"
    ok, report, page = await replay_skill(_S["page"], _S["context"], skill, params, _S["recorder"])
    _S["page"] = page
    _S["shot_seq"] += 1
    shot = await _shot(page, f"step_{_S['shot_seq']:04d}")
    record_skill_verification(skill["id"], ok, report[:180])
    try:
        state_after = await perceive(page)
        report += "\n\n" + format_state(state_after)
    except Exception as e:
        report += f"\n\n感知新状态失败: {str(e)[:100]}"
    if shot:
        report += f"\n\n截图: {shot}"
    return report


@mcp.tool()
async def auto_login() -> str:
    """用 .env 里的 AUTO_USERNAME/AUTO_PASSWORD 自动登录（密码登录页签）。
    前提：已 open_system 打开目标系统且当前停留在登录页。成功后自动保存登录态。
    若系统启用图形验证码/短信校验导致失败，转人工登录后调 save_login_state。"""
    if _S["page"] is None:
        return "错误：请先调用 open_system"
    if not AUTO_USERNAME or not AUTO_PASSWORD:
        return "错误：请在 .env 中配置 AUTO_USERNAME 和 AUTO_PASSWORD（填好后需重载 MCP）"
    page = _S["page"]
    if "/login" not in page.url:
        return f"当前不在登录页（{page.url[:80]}），无需登录。"
    steps = []
    try:
        # 切到密码登录页签（若已激活则忽略失败）
        try:
            await page.locator('text="密码登录"').first.click(timeout=4000)
            steps.append("切密码登录页签: 成功")
        except Exception:
            steps.append("切密码登录页签: 已激活")
        # 填账号密码（按占位符定位，与编号漂移无关）
        await page.get_by_placeholder("请输入您的帐号").fill(AUTO_USERNAME, timeout=8000)
        steps.append("填账号: 成功")
        await page.get_by_placeholder("请输入您的密码").fill(AUTO_PASSWORD, timeout=8000)
        steps.append("填密码: 成功（不回显）")
        # 勾选用户协议（页面唯一 checkbox；隐藏控件用 JS 兜底）
        try:
            cb = page.locator('input[type="checkbox"]')
            n = await cb.count()
            done = False
            for i in range(n):
                try:
                    if not await cb.nth(i).is_checked():
                        await cb.nth(i).check(timeout=2000, force=True)
                        done = True
                except Exception:
                    continue
            if not done:
                await page.evaluate(
                    "document.querySelectorAll('input[type=checkbox]').forEach(c=>{if(!c.checked)c.click()})"
                )
            steps.append("勾选用户协议: 成功")
        except Exception:
            steps.append("勾选用户协议: 未找到复选框（可能默认勾选）")
        # 提交表单：密码框内按 Enter（实测可靠）；无效再点登录按钮兜底
        try:
            await page.get_by_placeholder("请输入您的密码").press("Enter", timeout=4000)
            steps.append("回车提交: 成功")
        except Exception:
            steps.append("回车提交: 失败")
        await page.wait_for_timeout(5000)
        if "/login" in page.url:
            try:
                await page.get_by_text("登录", exact=True).first.click(timeout=6000)
                steps.append("点登录按钮兜底: 成功")
            except Exception:
                steps.append("点登录按钮兜底: 失败")
            await page.wait_for_timeout(5000)
        if "/login" in page.url:
            shot = await _shot(page, "auto_login_fail")
            if _S["recorder"] is not None:
                _S["recorder"].record("auto_login", ok=False, steps=steps)
            return (
                "自动登录未跳转，可能原因：密码错误/图形验证码/账号锁定。"
                f"步骤: {'；'.join(steps)}。请人工登录后调 save_login_state。截图: {shot}"
            )
        if _S["recorder"] is not None:
            _S["recorder"].record("auto_login", ok=True, steps=steps, url=page.url)
        try:
            await _S["context"].storage_state(path=str(STATE_FILE))
            steps.append("登录态已保存")
        except Exception:
            pass
        return f"自动登录成功: {page.url[:80]}\n步骤: {'；'.join(steps)}"
    except Exception as e:
        return f"自动登录失败: {str(e)[:150]}\n已完成步骤: {'；'.join(steps)}"


def main() -> None:
    """包入口（autolearn-mcp 命令 / python -m autolearn）：自检浏览器后启动 stdio 服务。"""
    from autolearn._bootstrap import install_browser

    install_browser()  # 缺内核时自动下载（进度走 stderr，不污染 MCP 协议）
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
# AI_GENERATE_END -------

