# AI_GENERATE_START -----
# -*- coding: utf-8 -*-
"""感知层：穿透 iframe 提取页面可交互元素，生成 LLM 可读的紧凑页面状态。

主框架排第 0 帧，其余 iframe 按出现顺序编号；元素编号全局唯一，
元素携带 frame 字段供执行层定位到正确的帧。
除标准控件外，还会扫描"有直接文本 + pointer 光标"的自定义容器（Element UI 等组件库的
菜单/页签多用 div 实现），避免顶部导航等关键入口漏识别。
"""

EXTRACT_JS = r"""
(offset) => {
  document.querySelectorAll('[data-al-id]').forEach(el => el.removeAttribute('data-al-id'));
  const seen = new Set();
  const els = [];
  const add = (el) => { if (el && !seen.has(el)) { seen.add(el); els.push(el); } };
  const SEL = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [role="checkbox"], [role="radio"], [role="switch"], [role="combobox"], [role="option"], [onclick], .el-menu-item, .el-submenu__title, .el-tabs__item, .el-dropdown-menu__item, .el-link, .el-checkbox, .el-radio, .el-switch, [class*="menu-item"], [class*="nav-item"], [class*="tab-item"]';
  document.querySelectorAll(SEL).forEach(add);
  // 自定义导航启发式：叶子容器 + 直接文本 + pointer 光标
  const customs = document.querySelectorAll('div, span, li, p');
  const maxScan = Math.min(customs.length, 800);
  for (let i = 0; i < maxScan && els.length < 400; i++) {
    const el = customs[i];
    if (el.closest('a, button, input, select, textarea')) continue;
    let hasText = false;
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) { hasText = true; break; }
    }
    if (!hasText) continue;
    let cs;
    try { cs = getComputedStyle(el); } catch (e) { continue; }
    if (cs.cursor === 'pointer') add(el);
  }
  const out = [];
  let seq = offset;
  for (const el of els) {
    if (out.length >= 150) break;
    if (el.disabled) continue;
    let rect;
    try { rect = el.getBoundingClientRect(); } catch (e) { continue; }
    if (!rect || rect.width < 2 || rect.height < 2) continue;
    if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, visibilityProperty: true })) continue;
    seq += 1;
    el.setAttribute('data-al-id', String(seq));
    const name = (el.getAttribute('aria-label') || el.innerText || el.value
      || el.getAttribute('placeholder') || el.title || el.getAttribute('name') || '')
      .trim().replace(/\s+/g, ' ').slice(0, 40);
    const tag = el.tagName.toLowerCase();
    const typ = el.getAttribute('type') || el.getAttribute('role') || '';
    const item = { idx: seq, tag: tag, name: name };
    if (typ) { item.type = typ; }
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      item.value = (typ === 'password') ? '***' : String(el.value || '').slice(0, 30);
    }
    if (tag === 'a' && el.getAttribute('href')) {
      item.href = el.getAttribute('href').slice(0, 80);
    }
    out.push(item);
  }
  return { count: seq - offset, elements: out };
}
"""

_MAX_FRAMES = 12  # 最多扫描的帧数，防止异常页面拖垮感知


async def perceive(page):
    """逐帧提取可交互元素。

    返回 {url, title, count, elements, frames}：
    - url/title 取主框架；elements 为全部元素（含 frame 帧号）；frames 为分帧摘要。
    """
    frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
    frames = frames[:_MAX_FRAMES]
    all_elements = []
    parts = []
    seq = 0
    for fi, frame in enumerate(frames):
        try:
            data = await frame.evaluate(EXTRACT_JS, seq)
        except Exception:
            continue  # 跨域/已销毁帧跳过
        if not data or not data["elements"]:
            continue
        for el in data["elements"]:
            el["frame"] = fi
        all_elements.extend(data["elements"])
        seq += data["count"]
        try:
            frame_url = frame.url
        except Exception:
            frame_url = ""
        parts.append({"index": fi, "url": frame_url, "count": data["count"]})
    try:
        main_url = page.url
        main_title = await page.title()
    except Exception:
        main_url, main_title = "", ""
    return {
        "url": main_url,
        "title": main_title,
        "count": seq,
        "elements": all_elements,
        "frames": parts,
    }


def format_state(state):
    """把页面状态格式化为注入 prompt 的文本（按帧分组）。"""
    lines = [f"URL: {state['url']}", f"标题: {state['title']}", f"可交互元素 {state['count']} 个:"]
    for part in state.get("frames", []):
        label = "主框架" if part["index"] == 0 else f"iframe-{part['index']}"
        lines.append(f"[{label}] {part['url']}（{part['count']} 个）:")
    if not state.get("frames"):
        lines.append("（当前页面未提取到任何可交互元素，可能整页都是 iframe 或仍在加载）")
        return "\n".join(lines)
    for el in state["elements"]:
        desc = f"[{el['idx']}] {el['tag']}"
        if el.get("type"):
            desc += f"[{el['type']}]"
        if el["name"]:
            desc += f" \"{el['name']}\""
        if el.get("value"):
            desc += f" value=\"{el['value']}\""
        lines.append(f"  (f{el['frame']}) " + desc)
    return "\n".join(lines)


def find_element(state, idx):
    """按编号查找元素描述；编号非法返回 None。"""
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return None
    for el in state["elements"]:
        if el["idx"] == idx:
            return el
    return None
# AI_GENERATE_END -----

