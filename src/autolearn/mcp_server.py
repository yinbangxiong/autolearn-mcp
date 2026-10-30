# AI_GENERATE_START ----------
# -*- coding: utf-8 -*-
"""autolearn MCP Server：把浏览器感知/执行/记录暴露为 MCP 工具（支持多系统学习）。

大脑由 AI 助手（Trae / Claude / Codex 等任何支持 MCP 的客户端）担任，
本服务只提供"眼睛"和"手"，并把探索过程沉淀为情景记忆。

多系统：open_system(system=已注册名 或 url=任意网址) 即可探索任何 Web 系统/网页；
登录态、凭据、语义记忆、操作技能、会话轨迹全部按系统自动归档（~/.autolearn/data/systems/<slug>/）。
跨系统通用内容写入 _global（任何系统可读写/回放）。

工具清单与推荐循环：
1. list_systems()             查看已注册系统（可选）
2. open_system(system|url, goal) 打开目标系统（自动创建会话记录；弹窗人工登录）
3. save_login_state()         登录完成后保存登录态（按系统归档），下次免登录
4. perceive_page()            读取当前页面可交互元素（自动截图）
5. act(action_json, thought)  执行一步动作，返回结果 + 最新页面状态
6. finish(summary, status)    结束会话，关闭浏览器，写 session_end
"""

import json
import re
import sys

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

from autolearn._bootstrap import launch_chromium
from autolearn.config import HEADLESS
from autolearn.desktop import DesktopBackend
from autolearn.executor import execute_action
from autolearn.perceive import find_element, format_state, perceive
from autolearn.recorder import SessionRecorder
from autolearn.reflect import (
    build_digest,
    load_skill,
    mark_processed,
    recall_all,
    recall as memory_recall,
    record_skill_verification,
    save_semantic,
    save_skill as reflect_save_skill,
)
from autolearn.skill_runner import replay_skill
from autolearn.systems import (
    GLOBAL_SYSTEM,
    LOGIN_SKILL_ID,
    get_credentials,
    list_systems as registered_systems,
    migrate_legacy,
    resolve_system,
    set_last_system,
    system_state_file,
)

mcp = FastMCP(
    "autolearn",
    instructions=(
        "多系统自动学习工具（Web + Windows 桌面应用）。循环用法："
        "open_system(system=已注册名 或 url=任意网址/app://应用名) 打开目标 → perceive_page 看页面 → "
        "act 执行动作 → 根据返回的最新状态继续决策 → finish 总结。"
        "桌面应用会话支持 click/click_text/type/select/scroll/key/drag（不支持 back 与技能回放）。"
        "登录态/记忆/技能按系统自动归档；探索完成用 export_memory_digest 导出轨迹、"
        "蒸馏后 save_semantic_memory / save_skill 沉淀（save_skill 用 system 参数归属系统）。"
        "act 的 idx 必须来自最近一次返回的元素列表。"
    ),
)

_S = {"pw": None, "browser": None, "context": None, "page": None, "recorder": None, "step": 0, "shot_seq": 0, "system": "", "backend": "web", "desktop": None}


async def _close_browser():
    """关闭浏览器/桌面绑定并清空会话状态（shot_seq 保留，避免跨会话截图序号回绕）。"""
    try:
        if _S["browser"] is not None:
            await _S["browser"].close()
        if _S["pw"] is not None:
            await _S["pw"].stop()
    except Exception:
        pass
    for k in ("pw", "browser", "context", "page", "recorder", "desktop"):
        _S[k] = None
    _S["step"] = 0
    _S["backend"] = "web"


async def _ensure_browser():
    if _S["browser"] is None:
        _S["pw"] = await async_playwright().start()
        _S["browser"] = await launch_chromium(_S["pw"], HEADLESS)
        state_file = system_state_file(_S["system"] or GLOBAL_SYSTEM)
        storage = str(state_file) if state_file.exists() else None
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


def _shot_desktop(be: DesktopBackend, name: str):
    """桌面窗口截图到当前会话目录，返回相对路径；失败不阻断。"""
    if _S["recorder"] is None:
        return None
    rel = f"shots/{name}.png"
    try:
        return rel if be.screenshot(_S["recorder"].dir / rel) else None
    except Exception:
        return None


@mcp.tool()
async def list_systems() -> str:
    """列出所有已注册的系统档案（URL / 记忆概况 / 登录态）。多系统探索前先调用确认目标。"""
    systems = registered_systems()
    if not systems:
        return "（尚无已注册系统。调用 open_system(url=...) 探索任意网页即可自动注册）"
    lines = []
    for s in systems:
        lines.append(
            f"- {s['name']}（{s['slug']}，{s['kind']}）| {s['url'] or '（未配置 url）'}"
            f" | 技能 {s['skills']} 个 | 知识节 {s['semantic_sections']} 个"
            f" | 登录态: {'已保存' if s['has_login_state'] else '无'}"
        )
    return "\n".join(lines)


@mcp.tool()
async def open_system(system: str = "", url: str = "", goal: str = "自由探索系统结构与功能") -> str:
    """打开目标系统/网页/桌面应用并开始一次探索会话。目标指定方式（优先级从高到低）：
    1. system：已注册系统名（见 list_systems）；
    2. url：任意网址——未注册的系统会自动注册档案，登录态/记忆按域名归档；
       桌面应用传 app://窗口标题（如 app://记事本），绑定指定窗口进行感知与操作；
    3. 都不传：上次打开的系统（首次使用 .env 的 TARGET_URL）。
    Web 会弹出浏览器窗口，可先人工完成登录再调 save_login_state()；
    桌面应用直接绑定现有窗口（应用需已打开）。"""
    slug, target, err = resolve_system(system, url)
    if slug is None:
        return f"错误：{err}"
    kind = "desktop" if target.lower().startswith("app://") else "web"
    cur = _S.get("backend", "web")
    # 切换系统或 backend 类型时清理旧绑定
    if _S["system"] != slug or cur != kind:
        if cur == "web" and _S["browser"] is not None:
            await _close_browser()
        elif cur == "desktop":
            _S["desktop"] = None
    _S["system"] = slug
    _S["backend"] = kind
    set_last_system(slug)

    if kind == "desktop":
        be = _S.get("desktop")
        if be is None:
            be = DesktopBackend()
            err2 = be.open(target)
            if err2:
                return f"错误：{err2}"
            _S["desktop"] = be
        state = be.perceive()
        if _S["recorder"] is None:
            _S["recorder"] = SessionRecorder(goal, slug)
        _S["step"] = 0
        shot = _shot_desktop(be, "current_view")
        out = (
            f"已绑定桌面窗口: {state['title']}\n系统: {slug}（桌面应用，记忆按此系统归档）\n"
            f"会话目录: {_S['recorder'].session_dir}\n"
        )
        if shot:
            out += f"截图: {shot}\n"
        out += "\n" + format_state(state)
        if state.get("error"):
            out += f"\n\n注意: {state['error']}"
        return out

    await _ensure_browser()
    if _S["page"] is None:
        _S["page"] = await _S["context"].new_page()
    await _S["page"].goto(target, wait_until="domcontentloaded", timeout=60000)
    if _S["recorder"] is None:
        _S["recorder"] = SessionRecorder(goal, slug)
    _S["step"] = 0
    state = await perceive(_S["page"])
    shot = await _shot(_S["page"], "current_view")
    out = (
        f"已打开: {target}\n系统: {slug}（登录态/记忆将按此系统归档）\n"
        f"会话目录: {_S['recorder'].session_dir}\n"
        f"截图: {shot}\n\n{format_state(state)}"
    )
    if state["count"] == 0 or re.search(r"login|signin|sso", target, re.I) or re.search(r"登录|请登陆", state.get("title", "") or ""):
        out += (
            "\n\n提示：若停留在登录页——已配置凭据可调用 auto_login() 自动登录；"
            "否则在浏览器窗口人工登录后调用 save_login_state()。"
        )
    return out


@mcp.tool()
async def save_login_state() -> str:
    """把当前浏览器会话的 Cookie/Storage 保存到当前系统的 state.json，下次打开该系统免登录。"""
    if _S["context"] is None:
        return "错误：请先调用 open_system"
    slug = _S["system"] or GLOBAL_SYSTEM
    path = system_state_file(slug)
    await _S["context"].storage_state(path=str(path))
    return f"登录态已保存（系统 {slug}）: {path}"


@mcp.tool()
async def perceive_page() -> str:
    """读取当前页面/窗口的可交互元素列表（自动截图 current_view.png）。
    元素编号 [n] 即 act 时用的 idx，编号以最近一次 perceive_page/act 返回为准。"""
    if _S.get("backend") == "desktop":
        be = _S.get("desktop")
        if be is None:
            return "错误：请先调用 open_system"
        state = be.perceive()
        shot = _shot_desktop(be, "current_view")
        out = format_state(state)
        if state.get("error"):
            out += f"\n\n注意: {state['error']}"
        if shot:
            out += f"\n\n截图: {shot}"
        return out
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
    """执行一步或一串浏览器/桌面动作，返回执行结果与最新页面状态。

    单动作 action_json 示例：
    {"action":"click","idx":3}
    {"action":"click_text","text":"流水认领"}
    {"action":"type","idx":5,"text":"报销单","press_enter":true}
    {"action":"select","idx":7,"value":"已审核"}
    {"action":"drag","from_idx":3,"to_idx":7}
    {"action":"drag","idx":5,"dx":300,"dy":0}
    {"action":"scroll","direction":"down"}
    {"action":"back"}                       ← 仅 Web
    {"action":"key","keys":"{Ctrl}s"}       ← 仅桌面（SendKeys 语法，{Enter}/{Ctrl}c 等）

    链式动作（一次调用内顺序执行，用于"点开下拉→点子项"等需连续操作的场景）：
    {"actions":[{"action":"click","idx":39},{"action":"click_text","text":"流水认领"}]}
    除第一步可用 idx 外，后续步骤建议全部用 click_text 按文本定位（下拉子项感知不到编号）。

    drag（拖拽）：元素拖到元素用 from_idx→to_idx（列表排序/穿梭框/树节点）；
    按偏移拖（滑块/缩放手势）用 idx 或 from_idx + dx/dy，dx/dy 可叠加在 to_idx 上微调落点。
    Web 支持跨 iframe（源/目标可各在不同 iframe）；桌面版仅限绑定窗口内。

    expect_name：第一步动作期望的元素名称关键字，防止编号漂移；对不上时自动按名称重匹配，
    匹配不到则不执行任何动作并返回最新页面状态。idx 必须来自最近一次 perceive_page/act 返回。"""
    if _S["page"] is None and _S.get("desktop") is None:
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

    if _S.get("backend") == "desktop":
        return await _act_desktop(plan, thought, expect_name)

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


async def _act_desktop(plan: list, thought: str, expect_name: str) -> str:
    """桌面模式动作执行：复用 recorder/编号防漂移逻辑，动作落 DesktopBackend。"""
    be = _S["desktop"]
    try:
        state_before = be.perceive()
    except Exception as e:
        return f"感知窗口失败: {str(e)[:120]}"
    if state_before.get("error"):
        return f"错误：{state_before['error']}\n\n{format_state(state_before)}"

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
                        f"错误：窗口上找不到名称含「{expect_name}」的控件，未执行任何动作。\n\n"
                        + format_state(state_before)
                    )

        ok, msg = be.act(action, params)
        _S["step"] += 1
        if _S["recorder"] is not None:
            _S["recorder"].record(
                "step",
                step=_S["step"],
                url=state_before["url"],
                title=state_before["title"],
                backend="desktop",
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

    _S["shot_seq"] += 1
    shot = _shot_desktop(be, f"step_{_S['shot_seq']:04d}")
    if _S["recorder"] is not None:
        _S["recorder"].record("step_shot", seq=_S["shot_seq"], path=shot, after_step=_S["step"])
    try:
        state_after = be.perceive()
    except Exception as e:
        return f"执行结果: {'；'.join(results)}{adjusted_note}\n感知新状态失败: {str(e)[:120]}"
    out = f"执行结果: {'；'.join(results)}{adjusted_note}\n\n{format_state(state_after)}"
    if state_after.get("error"):
        out += f"\n\n注意: {state_after['error']}"
    if shot:
        out += f"\n\n截图: {shot}"
    return out


@mcp.tool()
async def finish(summary: str = "", status: str = "done") -> str:
    """结束本次探索会话：写入 session_end 并关闭浏览器/解除窗口绑定。status 可选 done/stopped。"""
    mem_path = None
    if _S["recorder"] is not None:
        _S["recorder"].record("session_end", status=status, summary=summary)
        mem_path = str(_S["recorder"].file)
    await _close_browser()
    return f"会话已结束。情景记忆: {mem_path}"


@mcp.tool()
async def export_memory_digest(max_sessions: int = 5, system: str = "") -> str:
    """导出未消化的探索会话蒸馏摘要（情景记忆 → 大脑），按系统归档。
    system 为空：有当前会话系统则导出该系统；否则导出所有系统的未消化会话。
    大脑据此总结出页面知识与操作技能，调用 save_semantic_memory / save_skill 沉淀
    （save_skill 传 system 归属到对应系统），完成后调用 mark_sessions_processed 标记已消化。"""
    if system:
        digest, names = build_digest(system, max_sessions)
        header = f"【{system}】待消化会话 {len(names)} 个: {', '.join(names)}\n\n" if names else ""
        return header + digest
    if _S["system"]:
        digest, names = build_digest(_S["system"], max_sessions)
        header = f"待消化会话 {len(names)} 个: {', '.join(names)}\n\n" if names else ""
        return header + digest
    parts = []
    for s in registered_systems():
        if s["slug"] == GLOBAL_SYSTEM:
            continue
        digest, names = build_digest(s["slug"], max_sessions)
        if names:
            parts.append(f"【{s['slug']}】待消化会话 {len(names)} 个: {', '.join(names)}\n\n{digest}")
    return "\n\n".join(parts) if parts else "（所有系统均无待消化会话）"


@mcp.tool()
async def save_semantic_memory(title: str, content: str, source: str = "", system: str = "") -> str:
    """把蒸馏出的语义知识（页面结构/业务规则/操作要点/网站知识）写入语义记忆，按系统归档。
    system 为空默认写入当前会话系统；传 "_global" 写入跨系统通用记忆（任何系统可见）。
    title 建议形如「页面｜单据设计器」「知识｜XX网站导航结构」，同名节会被整体更新。"""
    slug = system or _S["system"] or GLOBAL_SYSTEM
    path = save_semantic(title, content, source, slug)
    return f"语义记忆已写入（系统 {slug}）: {path}\n节标题: {title}"


@mcp.tool()
async def save_skill(name: str, description: str, steps_json: str, source: str = "", system: str = "") -> str:
    """把蒸馏出的可复用操作技能写入程序记忆，按系统归档。
    system 为空默认归属当前会话系统（仅该系统可回放）；传 "_global" 则任何系统均可回放。
    steps_json 示例：
    [{"action":"click_text","text":"配置平台"},
     {"action":"click_text","text":"表单配置"}]
    步骤定位优先用 text（稳定），不要用探索时的临时编号 idx。
    登录技能请命名为 "login"（auto_login 失败时会自动回放该技能，步骤可用 {{username}}/{{password}} 占位符）。"""
    try:
        steps = json.loads(steps_json)
        if not isinstance(steps, list):
            raise ValueError("not a list")
    except (json.JSONDecodeError, ValueError) as e:
        return f"错误：steps_json 不是合法的 JSON 数组: {e}"
    slug = system or _S["system"] or GLOBAL_SYSTEM
    path = reflect_save_skill(name, description, steps, source, slug)
    return f"技能已保存（系统 {slug}）: {path}"


@mcp.tool()
async def mark_sessions_processed(session_names: str) -> str:
    """把已蒸馏完成的会话标记为已消化（逗号分隔的会话目录名），自动定位所属系统索引。"""
    names = [n.strip() for n in session_names.split(",") if n.strip()]
    count = mark_processed(names)
    return f"已标记 {count} 个会话为已消化"


@mcp.tool()
async def recall(query: str = "", system: str = "") -> str:
    """检索沉淀的记忆（语义知识 + 操作技能），任务开始前调用以注入历史经验。
    system 为空：有当前会话系统则查该系统（附带跨系统通用记忆），否则跨全部系统检索。
    可显式传 system 指定系统，或 system="_global" 只查通用记忆。"""
    if system:
        return memory_recall(query, system)
    if _S["system"]:
        return memory_recall(query, _S["system"])
    if query:
        return recall_all(query)
    return memory_recall("")


@mcp.tool()
async def run_skill(skill_id: str, params_json: str = "{}") -> str:
    """回放程序记忆中的技能（自动执行步骤并逐步自愈与校验）。
    skill_id 支持技能 id 或名称（如「进入平台子模块」）；优先在当前会话系统查找，
    找不到再查跨系统通用技能（_global）；归属其他系统的技能会被拒绝，防止跨系统误操作。
    params_json 为技能参数，如 {"platform": "业财融合", "module": "流水认领"}。
    需先 open_system 打开对应系统。回放成功会累计技能 verified 次数，失败记录 history。
    桌面应用会话暂不支持技能回放（后续版本支持），可直接 perceive_page + act 操作。"""
    if _S["page"] is None and _S.get("desktop") is None:
        return "错误：请先调用 open_system"
    if _S.get("backend") == "desktop":
        return "错误：桌面应用会话暂不支持技能回放（后续版本支持），可直接 perceive_page + act 操作。"
    slug = _S["system"] or GLOBAL_SYSTEM
    skill = load_skill(skill_id, slug)
    if skill is None:
        # 当前系统/通用记忆都没有：探测是否归属其他系统，给出明确拒绝提示
        for s in registered_systems():
            if s["slug"] in (slug, GLOBAL_SYSTEM):
                continue
            cand = load_skill(skill_id, s["slug"])
            if cand is not None and (cand.get("system") or GLOBAL_SYSTEM) == s["slug"]:
                return (
                    f"错误：技能「{skill_id}」归属系统「{s['slug']}」，与当前系统「{slug}」不一致，已拒绝回放。\n"
                    f"如确需执行，请先 open_system(system=\"{s['slug']}\")。"
                )
        return f"错误：找不到技能「{skill_id}」。\n\n{memory_recall('', slug)}"
    sk_sys = skill.get("system") or GLOBAL_SYSTEM
    if sk_sys not in (slug, GLOBAL_SYSTEM):
        return (
            f"错误：技能「{skill_id}」归属系统「{sk_sys}」，与当前系统「{slug}」不一致，已拒绝回放。\n"
            f"如确需执行，请先 open_system(system=\"{sk_sys}\")。"
        )
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
    record_skill_verification(skill["id"], ok, report[:180], sk_sys)
    try:
        state_after = await perceive(page)
        report += "\n\n" + format_state(state_after)
    except Exception as e:
        report += f"\n\n感知新状态失败: {str(e)[:100]}"
    if shot:
        report += f"\n\n截图: {shot}"
    return report


# ---------------- 自动登录（通用策略链 + 登录技能回放） ----------------

_USERNAME_HINTS = [
    'input[placeholder*="帐号" i]', 'input[placeholder*="账号" i]', 'input[placeholder*="用户名" i]',
    'input[placeholder*="用户" i]', 'input[placeholder*="邮箱" i]', 'input[placeholder*="手机" i]',
    'input[placeholder*="user" i]', 'input[placeholder*="email" i]', 'input[placeholder*="phone" i]',
    'input[name*="user" i]', 'input[name*="account" i]', 'input[name*="email" i]', 'input[name*="phone" i]',
    'input[name*="mobile" i]', 'input[id*="user" i]', 'input[id*="account" i]',
    'input[type="email"]:visible', 'input[type="tel"]:visible', 'input[type="text"]:visible',
]
_SUBMIT_SELECTORS = [
    'button[type="submit"]', 'input[type="submit"]',
    'button:has-text("登录")', 'button:has-text("登 录")', 'a:has-text("登录")',
    'button:has-text("Sign in")', 'button:has-text("Log in")', 'button:has-text("Login")',
]

# 密码框之前最近的可见文本类输入框（DOM 邻近兜底，适配任意布局）
_PROXIMITY_JS = """() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const pwds = [...document.querySelectorAll('input[type=password]')].filter(visible);
  if (!pwds.length) return null;
  const pwd = pwds[0];
  const type = el => (el.getAttribute('type') || 'text').toLowerCase();
  const cands = [...document.querySelectorAll('input')].filter(el =>
    visible(el) && !el.disabled && !el.readOnly && ['text', 'email', 'tel', ''].includes(type(el)));
  const before = cands.filter(el => el.compareDocumentPosition(pwd) & Node.DOCUMENT_POSITION_FOLLOWING);
  return before.length ? before[before.length - 1] : null;
}"""


async def _find_username_input(page):
    for sel in _USERNAME_HINTS:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    try:
        handle = await page.evaluate_handle(_PROXIMITY_JS)
        el = handle.as_element() if handle else None
        if el is not None:
            return el
    except Exception:
        pass
    return None


async def _generic_login(page, cred: dict) -> tuple[bool, list]:
    """通用登录策略链：找账号/密码框 → 填入 → 勾协议 → 提交 → 验跳转。返回 (是否成功, 步骤记录)。"""
    steps = []
    try:
        # 常见页签切换（如「密码登录」），失败忽略
        try:
            tab = page.get_by_text(re.compile(r"密码登录|账号登录|账密登录|帐号登录"))
            if await tab.count() > 0:
                await tab.first.click(timeout=3000)
                steps.append("切密码登录页签: 成功")
        except Exception:
            pass
        pwd = page.locator('input[type="password"]:visible')
        if await pwd.count() == 0:
            return False, ["未找到可见的密码输入框（可能已登录或不是登录页）"]
        user = await _find_username_input(page)
        if user is None:
            return False, ["未找到用户名输入框"]
        await user.fill(cred["username"], timeout=8000)
        steps.append("填账号: 成功")
        await pwd.first.fill(cred["password"], timeout=8000)
        steps.append("填密码: 成功（不回显）")
        # 勾选协议/记住我等 checkbox（隐藏控件用 JS 兜底）
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
            steps.append("勾选协议复选框: 成功")
        except Exception:
            steps.append("勾选协议复选框: 未找到（可能默认勾选）")
        # 提交：按钮 selector 链 → 密码框回车兜底
        submitted = False
        for sel in _SUBMIT_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible():
                    await btn.click(timeout=3000)
                    steps.append(f"提交({sel}): 成功")
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            await pwd.first.press("Enter", timeout=4000)
            steps.append("回车提交: 成功")
        # 等待跳转：URL 变化且密码框消失（最长 ~12 秒）
        login_url = page.url
        for _ in range(12):
            await page.wait_for_timeout(1000)
            if await page.locator('input[type="password"]:visible').count() > 0 and page.url == login_url:
                return False, steps
        if await page.locator('input[type="password"]:visible').count() == 0:
            return True, steps
        return False, steps
    except Exception as e:
        steps.append(f"异常: {str(e)[:120]}")
        return False, steps


@mcp.tool()
async def auto_login() -> str:
    """自动登录当前系统。策略链：1) 通用登录（凭据取 ~/.autolearn/credentials.json 中该系统条目，
    回退 .env 全局 AUTO_USERNAME/AUTO_PASSWORD）；2) 失败则回放该系统 "login" 技能（首次人工登录后
    用 save_skill 沉淀，步骤可用 {{username}}/{{password}} 占位符）；3) 仍失败转人工登录后调 save_login_state。
    成功后自动保存该系统登录态。图形验证码/短信校验场景请直接人工登录。"""
    if _S["page"] is None:
        return "错误：请先调用 open_system"
    slug = _S["system"] or GLOBAL_SYSTEM
    cred = get_credentials(slug)
    page = _S["page"]
    shot = await _shot(page, "auto_login")
    if not cred:
        return (
            f"错误：系统「{slug}」未配置登录凭据。两种方式：\n"
            f'1. 在 ~/.autolearn/credentials.json 添加 {{"{slug}": {{"username": "账号", "password": "密码"}}}}（立即生效）；\n'
            "2. 配置 .env 全局 AUTO_USERNAME/AUTO_PASSWORD（需重载 MCP）。\n"
            "或人工登录后调用 save_login_state。截图: " + str(shot)
        )
    steps = []
    if re.search(r"login|signin|sso", page.url, re.I) or await page.locator('input[type="password"]:visible').count() > 0:
        ok, steps = await _generic_login(page, cred)
    else:
        ok = False
        steps = ["当前页面无登录表单"]
    # 通用策略失败 → 回放该系统 login 技能（自愈 + 校验）
    if not ok:
        skill = load_skill(LOGIN_SKILL_ID, slug)
        if skill is not None:
            ok, report, page = await replay_skill(
                page, _S["context"], skill,
                {"username": cred["username"], "password": cred["password"]},
                _S["recorder"],
            )
            steps.append(f"回放登录技能「{skill.get('name')}」: {'成功' if ok else '失败（' + report[:100] + '）'}")
            _S["page"] = page
    if not ok:
        shot = await _shot(page, "auto_login_fail")
        if _S["recorder"] is not None:
            _S["recorder"].record("auto_login", ok=False, steps=steps, system=slug)
        return (
            "自动登录失败，可能原因：密码错误/图形验证码/短信校验/特殊登录布局。"
            f"步骤: {'；'.join(steps)}。请人工登录后调 save_login_state。截图: {shot}"
        )
    if _S["recorder"] is not None:
        _S["recorder"].record("auto_login", ok=True, steps=steps, url=page.url, system=slug)
    saved = ""
    try:
        await _S["context"].storage_state(path=str(system_state_file(slug)))
        saved = "；登录态已保存"
    except Exception:
        pass
    return f"自动登录成功: {page.url[:80]}\n步骤: {'；'.join(steps)}{saved}"


def main() -> None:
    """包入口（autolearn-mcp 命令 / python -m autolearn）：迁移旧数据、自检浏览器后启动 stdio 服务。"""
    from autolearn._bootstrap import install_browser

    msg = migrate_legacy()  # 旧版单系统数据一次性迁入默认系统档案（幂等）
    if msg:
        print(f"[autolearn] {msg}", file=sys.stderr)  # MCP stdio：进度/日志走 stderr
    install_browser()  # 缺内核时自动下载（进度走 stderr，不污染 MCP 协议）
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
# AI_GENERATE_END ----------
