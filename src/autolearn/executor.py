# AI_GENERATE_START -----
# -*- coding: utf-8 -*-
"""动作执行层：把 AI 助手/LLM 决定的动作落到浏览器上（async，CLI 与 MCP 共用）。

元素类动作（click/type/select/click_text）支持在 iframe 内执行：传入 frame（Playwright Frame 对象）；
页面级动作（scroll/back）始终作用于 page。click_text 按精确文本定位，主框架找不到时遍历 iframe。
drag（拖拽）内部按 data-al-id 跨帧自定位（data-al-id 全局唯一），源/目标可各在不同 iframe，不依赖 frame 参数。
"""


async def _al_id_locator(page, idx):
    """按 data-al-id 跨帧定位元素（主框架优先，再遍历 iframe）。找不到返回 None。"""
    sel = f'[data-al-id="{int(idx)}"]'
    loc = page.locator(sel)
    try:
        if await loc.count() > 0:
            return loc
    except Exception:
        pass
    for fr in page.frames:
        if fr is page.main_frame:
            continue
        try:
            floc = fr.locator(sel)
            if await floc.count() > 0:
                return floc
        except Exception:
            continue
    return None


async def _do_drag(page, src, dst_loc=None, dx=0.0, dy=0.0):
    """鼠标轨迹拖拽：源中心按下，渐进移动到目标点后松开。

    dst_loc 为空时目标点 = 源中心 + (dx, dy)；否则 = 目标元素中心 + (dx, dy)。
    适用于 sortablejs/vuedraggable/滑块等鼠标事件类拖拽；HTML5 原生 DnD
    （draggable=true）在 Chromium 下裸鼠标不触发 drop，走 _html5_dnd。
    返回 (是否成功, 结果说明)。
    """
    try:
        await src.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    sbox = await src.bounding_box()
    if not sbox:
        return False, "拖拽源元素不可见或无边界框，无法拖拽"
    sx, sy = sbox["x"] + sbox["width"] / 2, sbox["y"] + sbox["height"] / 2
    if dst_loc is not None:
        try:
            await dst_loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        tbox = await dst_loc.bounding_box()
        if not tbox:
            return False, "拖拽目标元素不可见或无边界框，无法拖拽"
        tx, ty = tbox["x"] + tbox["width"] / 2 + dx, tbox["y"] + tbox["height"] / 2 + dy
    else:
        tx, ty = sx + dx, sy + dy
    mouse = page.mouse
    await mouse.move(sx, sy)
    await mouse.down()
    # 按下后先微移触发 dragstart，再分步渐进移动到目标
    await mouse.move(sx + (3 if tx >= sx else -3), sy + (3 if ty >= sy else -3), steps=2)
    step_count = 12
    for i in range(1, step_count + 1):
        await mouse.move(sx + (tx - sx) * i / step_count, sy + (ty - sy) * i / step_count)
    await mouse.move(tx, ty)
    await mouse.up()
    return True, "成功"


# HTML5 原生 DnD：合成 DragEvent 序列（裸鼠标/官方 drag_to 在部分 Chromium 环境不触发 drop）
_HTML5_DND_SAME_JS = """({s, d, dx, dy}) => {
  const r = d.getBoundingClientRect();
  const o = { bubbles: true, cancelable: true, dataTransfer: new DataTransfer(),
    clientX: r.left + r.width / 2 + dx, clientY: r.top + r.height / 2 + dy };
  const dt = o.dataTransfer;
  s.dispatchEvent(new DragEvent('dragstart', o));
  // 页面未在 dragstart 写数据时，用源元素文本兜底，保证 drop 端 getData 有值
  if (!dt.getData('text/plain') && (s.innerText || '').trim()) {
    dt.setData('text/plain', s.innerText.trim());
  }
  d.dispatchEvent(new DragEvent('dragenter', o));
  d.dispatchEvent(new DragEvent('dragover', o));
  d.dispatchEvent(new DragEvent('drop', o));
  s.dispatchEvent(new DragEvent('dragend', o));
  return dt.getData('text/plain') || '';
}"""

_HTML5_DND_START_JS = """(s) => {
  const dt = new DataTransfer();
  s.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
  return dt.getData('text/plain') || (s.innerText || '').trim();
}"""

_HTML5_DND_DROP_JS = """({d, t, dx, dy}) => {
  const r = d.getBoundingClientRect();
  const dt = new DataTransfer();
  if (t) { dt.setData('text/plain', t); }
  const o = { bubbles: true, cancelable: true, dataTransfer: dt,
    clientX: r.left + r.width / 2 + dx, clientY: r.top + r.height / 2 + dy };
  d.dispatchEvent(new DragEvent('dragenter', o));
  d.dispatchEvent(new DragEvent('dragover', o));
  d.dispatchEvent(new DragEvent('drop', o));
}"""

_HTML5_DND_END_JS = "(s) => s.dispatchEvent(new DragEvent('dragend', { bubbles: true, cancelable: true }))"

# HTML5 偏移拖拽：无目标编号时，以源中心 + (dx,dy) 为落点，elementFromPoint 就地取目标元素，
# 在源元素所在帧内合成完整 DnD 序列（表单设计器"从面板拖组件进画布"等自由落点场景）
_HTML5_DND_OFFSET_JS = """({s, dx, dy}) => {
  const r = s.getBoundingClientRect();
  const sx = r.left + r.width / 2, sy = r.top + r.height / 2;
  const tx = sx + dx, ty = sy + dy;
  const dt = new DataTransfer();
  s.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: sx, clientY: sy }));
  if (!dt.getData('text/plain') && (s.innerText || '').trim()) {
    dt.setData('text/plain', s.innerText.trim());
  }
  const target = document.elementFromPoint(tx, ty);
  if (!target) {
    s.dispatchEvent(new DragEvent('dragend', { bubbles: true, cancelable: true }));
    return 'NO_TARGET';
  }
  const o = { bubbles: true, cancelable: true, dataTransfer: dt, clientX: tx, clientY: ty };
  target.dispatchEvent(new DragEvent('dragenter', o));
  target.dispatchEvent(new DragEvent('dragover', o));
  target.dispatchEvent(new DragEvent('drop', o));
  s.dispatchEvent(new DragEvent('dragend', o));
  return 'OK:' + target.tagName + '.' + String(target.className || '').slice(0, 50);
}"""


async def _html5_dnd_offset(src, dx=0.0, dy=0.0):
    """HTML5 偏移拖拽：无目标编号时按源中心 + (dx,dy) 落点合成 DnD。

    落点元素由 elementFromPoint 实时解析，全程在源元素所在帧内执行（坐标天然同帧）。
    返回 (是否成功, 结果说明)；成功时说明含落点元素 tag.class 便于判断落点。
    """
    try:
        sh = await src.element_handle()
        if sh is None:
            return False, "拖拽源元素已失效，无法拖拽"
        sf = await sh.owner_frame()
        if sf is None:
            return False, "无法确定拖拽源所在帧"
        res = await sf.evaluate(_HTML5_DND_OFFSET_JS, {"s": sh, "dx": dx, "dy": dy})
        if isinstance(res, str) and res.startswith("OK:"):
            return True, res
        return False, f"HTML5 偏移拖拽未命中落点元素: {res}"
    except Exception as e:
        return False, f"HTML5 偏移拖拽失败: {str(e)[:100]}"


async def _html5_dnd(src, dst, dx=0.0, dy=0.0):
    """HTML5 原生拖拽（源元素 draggable=true）：合成 DnD 事件序列。

    同帧时源/目标共享一个 DataTransfer（页面 dragstart 写入的数据 drop 可读）；
    跨帧（含跨域 iframe）时目标帧用独立 DataTransfer 并以源文本兜底 setData。
    返回 (是否成功, 结果说明)。
    """
    try:
        sh = await src.element_handle()
        dh = await dst.element_handle()
        if sh is None or dh is None:
            return False, "拖拽源/目标元素已失效，无法拖拽"
        sf, df = await sh.owner_frame(), await dh.owner_frame()
        if sf is not None and sf is df:
            await sf.evaluate(_HTML5_DND_SAME_JS, {"s": sh, "d": dh, "dx": dx, "dy": dy})
        else:
            text = await sf.evaluate(_HTML5_DND_START_JS, sh)
            await df.evaluate(_HTML5_DND_DROP_JS, {"d": dh, "t": text, "dx": dx, "dy": dy})
            await sf.evaluate(_HTML5_DND_END_JS, sh)
        return True, "成功"
    except Exception as e:
        return False, f"HTML5 拖拽失败: {str(e)[:100]}"


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
        elif action == "drag":
            src_idx = params.get("from_idx", params.get("idx"))
            if src_idx is None:
                return False, "drag 缺少 from_idx（或 idx）参数", page
            src = await _al_id_locator(page, src_idx)
            if src is None:
                return False, f"未找到编号 {src_idx} 对应的拖拽源元素（可先 perceive_page 刷新编号）", page
            dst = None
            if params.get("to_idx") is not None:
                dst = await _al_id_locator(page, params.get("to_idx"))
                if dst is None:
                    return False, f"未找到编号 {params.get('to_idx')} 对应的拖拽目标元素", page
            try:
                dx = float(params.get("dx") or 0)
                dy = float(params.get("dy") or 0)
            except (TypeError, ValueError):
                return False, "drag 的 dx/dy 必须是数字", page
            if dst is None and dx == 0 and dy == 0:
                return False, "drag 需要提供 to_idx 或 dx/dy 之一", page
            if dst is not None:
                # 源元素是 HTML5 原生拖拽（draggable=true）时优先合成 DnD 事件，鼠标轨迹兜底；
                # 否则直接走鼠标轨迹（sortablejs/vuedraggable/滑块等鼠标事件类拖拽）
                try:
                    draggable = await src.evaluate("el => !!el.closest('[draggable=\"true\"]')")
                except Exception:
                    draggable = False
                ok2, msg2 = (False, "")
                if draggable:
                    ok2, msg2 = await _html5_dnd(src, dst, dx, dy)
                if not ok2:
                    ok2, msg2 = await _do_drag(page, src, dst, dx, dy)
                if not ok2:
                    return False, msg2, page
            else:
                # 无目标编号的偏移拖拽：HTML5 源（draggable=true）优先按落点合成 DnD，
                # 裸鼠标轨迹对这类源不触发 drop（会变成文本框选）；失败再回退鼠标轨迹
                try:
                    draggable = await src.evaluate("el => !!el.closest('[draggable=\"true\"]')")
                except Exception:
                    draggable = False
                if draggable:
                    ok2, msg2 = await _html5_dnd_offset(src, dx, dy)
                    if ok2:
                        return True, msg2, page
                ok2, msg2 = await _do_drag(page, src, None, dx, dy)
                if not ok2:
                    return False, msg2, page
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
# AI_GENERATE_END -----

