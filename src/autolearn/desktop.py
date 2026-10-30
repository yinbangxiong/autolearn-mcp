# AI_GENERATE_START -
# -*- coding: utf-8 -*-
"""桌面应用 Backend（Windows）：基于 UI Automation（uiautomation）的感知与执行。

设计要点：
- 指定窗口绑定（app://窗口标题或类名主体），感知/操作仅限该窗口，安全可控；
- 控件树遍历 → 交互元素编号（使用方式与 Web 的 data-al-id 编号体系一致）；
- act 时元素重定位用「特征匹配」：(tag, name, automation_id, class_name) + 同特征序号，
  对动态控件树比控件树路径法更稳；匹配失败按名称包含兜底（自愈）；
- 执行优先真实鼠标/键盘事件（兼容自绘控件），Edit 输入优先 ValuePattern（原生支持中文）；
- 窗口截图用 CaptureToImage，失败不阻断探索。
- 仅 Windows 可用；非 Windows 或未安装 uiautomation 时 open 返回明确提示。

支持动作（与 Web 动作集对齐 + 桌面特有）：
- click {idx} / click_text {text}
- type {idx, text, press_enter}
- select {idx, value}（ComboBox）
- scroll {direction: down|up}
- key {keys}（SendKeys 语法，如 "{Ctrl}s"、"{Enter}"）
- drag {from_idx, to_idx} 或 {idx, dx, dy}
"""

import ctypes
import sys
import time
from pathlib import Path

try:
    import uiautomation as auto
except Exception:  # 非 Windows 或未安装依赖
    auto = None

MAX_NODES = 250     # 单次感知最多收集的控件节点数
MAX_DEPTH = 10      # 控件树最大遍历深度
WALK_TIMEOUT = 8.0  # 单次感知超时（秒），防止异常应用拖垮会话

# 会收集为可交互元素的 ControlType（去 Control 后缀小写）
_INTERACTIVE = {
    "button", "menuitem", "tabitem", "hyperlink", "edit", "combobox",
    "checkbox", "radiobutton", "listitem", "treeitem", "slider",
    "splitbutton", "spinner", "toggleswitch", "dataitem",
    "list", "tab", "tree", "document",
}
# 即使无 Name 也值得收集的类型（搜索框/空列表/富文本编辑区等）
_NAMELESS_OK = {"edit", "combobox", "list", "tab", "tree", "document"}
# Edit/ComboBox/Document 才读取当前值（ValuePattern 有 COM 开销）
_VALUE_TYPES = {"edit", "combobox", "document"}

# 任务栏/桌面等系统窗口不列入可选窗口
_SYSTEM_CLASSES = {"Shell_TrayWnd", "Progman", "WorkerW", "Shell_SecondaryTrayWnd"}


def is_available() -> bool:
    return auto is not None and sys.platform == "win32"


def list_windows_all() -> list:
    """返回 (Control, Name, ClassName) 列表（可见顶层窗口，系统窗口除外）。"""
    result = []
    if auto is None:
        return result
    try:
        for w in auto.GetRootControl().GetChildren():
            try:
                if w.IsOffscreen:
                    continue
                cls = w.ClassName or ""
                if cls in _SYSTEM_CLASSES:
                    continue
                name = (w.Name or "").strip()
                if not name:
                    continue
                result.append((w, name, cls))
            except Exception:
                continue
    except Exception:
        pass
    return result


def list_windows() -> list[dict]:
    """枚举当前可见的顶层窗口（供绑定失败时提示大脑选择）。"""
    return [
        {"name": name, "class": cls, "type": w.ControlTypeName}
        for w, name, cls in list_windows_all()
    ]


def find_window(target: str):
    """按标题/类名子串（大小写不敏感）查找可见顶层窗口，返回 Control 或 None。"""
    t = (target or "").strip().lower()
    if not t:
        return None
    for w, name, cls in list_windows_all():
        if t in name.lower() or t in cls.lower():
            return w
    return None


_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_CAPTION = 0x00C00000
_WS_EX_TOOLWINDOW = 0x00000080


def _popup_like(w) -> bool:
    """判定顶层窗口是否为弹出层（菜单/下拉/浮出控件），而非应用的多开主窗口。

    依据原生窗口样式：无边框（无 WS_CAPTION）或 WS_EX_TOOLWINDOW 视为 popup；
    无原生句柄的 UIA 窗口节点（纯虚拟窗口）按 popup 收集。
    """
    try:
        hwnd = w.NativeWindowHandle
    except Exception:
        hwnd = 0
    if not hwnd:
        return True
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, _GWL_STYLE)
        ex = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        return not (style & _WS_CAPTION) or bool(ex & _WS_EX_TOOLWINDOW)
    except Exception:
        return True


class DesktopBackend:
    """一个实例绑定一个应用窗口，提供感知/执行/截图。"""

    def __init__(self):
        self.window = None   # 绑定的顶层窗口 Control
        self._cache = {}     # idx -> (tag, name, automation_id, class_name, occurrence)

    # ---------- 窗口管理 ----------

    def open(self, target: str) -> str:
        """绑定窗口。target 为窗口标题/类名子串。成功返回空串，失败返回错误说明。"""
        if not is_available():
            return "桌面自动化仅支持 Windows，且需安装 uiautomation 依赖（pip install uiautomation）"
        target = (target or "").strip()
        if target.lower().startswith("app://"):
            target = target[6:].strip("/")
        if not target:
            wins = list_windows()
            listing = "\n".join(f"- {x['name']}（{x['class']}）" for x in wins[:15])
            return "未指定应用窗口。当前可见顶层窗口:\n" + (listing or "（无）")
        w = find_window(target)
        if w is None:
            wins = list_windows()
            listing = "\n".join(f"- {x['name']}（{x['class']}）" for x in wins[:15])
            return f"未找到标题或类名含「{target}」的可见窗口。当前可见顶层窗口:\n{listing or '（无）'}"
        self.window = w
        self._cache = {}
        return ""

    def _check_window(self) -> str:
        if self.window is None:
            return "错误：请先 open_system(url=\"app://应用名\") 绑定窗口"
        try:
            if not self.window.Exists(0.5, 0.5):
                return "错误：绑定的窗口已关闭，请重新 open_system 绑定"
        except Exception:
            return "错误：窗口句柄失效，请重新 open_system 绑定"
        return ""

    # ---------- 感知 ----------

    def _collect(self):
        """遍历控件树，返回 (elements, ctrls, sigs)。

        elements 为输出 dict 列表（不含 idx）；ctrls 为对应 Control 引用；
        sigs 为对应 (key, occurrence) 特征签名，供 act 重定位。
        除绑定窗口子树外，附带同进程的 popup 窗口（下拉/菜单弹出层是独立顶层窗口）。
        """
        elements, ctrls, sigs = [], [], []
        sig_count = {}
        counter = [0]
        deadline = time.time() + WALK_TIMEOUT
        seen_hwnds = set()  # 已遍历窗口句柄：UIA 每次遍历返回新包装对象，is 比较失效，须按 hwnd 去重
        try:
            hwnd0 = self.window.NativeWindowHandle
            if hwnd0:
                seen_hwnds.add(hwnd0)
        except Exception:
            pass

        def walk(ctrl, depth):
            try:
                hwnd = ctrl.NativeWindowHandle
            except Exception:
                hwnd = 0
            if hwnd:
                seen_hwnds.add(hwnd)
            if time.time() > deadline or counter[0] >= MAX_NODES:
                return
            try:
                children = ctrl.GetChildren()
            except Exception:
                return
            for ch in children:
                counter[0] += 1
                if time.time() > deadline or counter[0] >= MAX_NODES:
                    return
                try:
                    tname = ch.ControlTypeName
                except Exception:
                    continue
                tag = tname[:-7].lower() if tname.endswith("Control") else tname.lower()
                try:
                    off = ch.IsOffscreen
                except Exception:
                    off = True
                if off:
                    continue  # 不可见控件连同子树跳过（折叠面板），提速
                if tag in _INTERACTIVE:
                    try:
                        enabled = ch.IsEnabled
                    except Exception:
                        enabled = False
                    if enabled:
                        name = ""
                        try:
                            name = (ch.Name or "").strip()
                        except Exception:
                            pass
                        if name or tag in _NAMELESS_OK:
                            aid = cls = ""
                            try:
                                aid = ch.AutomationId or ""
                            except Exception:
                                pass
                            try:
                                cls = ch.ClassName or ""
                            except Exception:
                                pass
                            value = ""
                            if tag in _VALUE_TYPES:
                                try:
                                    value = str(ch.GetValuePattern().Value)[:60]
                                except Exception:
                                    pass
                            key = (tag, name, aid, cls)
                            occ = sig_count.get(key, 0)
                            sig_count[key] = occ + 1
                            elements.append(
                                {"tag": tag, "name": name[:60], "value": value,
                                 "automation_id": aid[:40], "class_name": cls[:40]}
                            )
                            ctrls.append(ch)
                            sigs.append((key, occ))
                if depth < MAX_DEPTH:
                    walk(ch, depth + 1)

        walk(self.window, 0)
        # 同进程弹出层（菜单/下拉/浮出控件）：不在绑定窗口子树内，补充遍历。
        # 注意：UIA 每次遍历返回新包装对象，is 比较失效——按 NativeWindowHandle 去重；
        # 应用多开的主窗口（有标题栏）不算弹出层，用窗口样式精确过滤。
        try:
            my_pid = self.window.ProcessId
            for w in auto.GetRootControl().GetChildren():
                try:
                    if w.IsOffscreen:
                        continue
                    try:
                        hwnd = w.NativeWindowHandle
                    except Exception:
                        hwnd = 0
                    if hwnd and hwnd in seen_hwnds:
                        continue  # 绑定窗口自身或已遍历过的顶层窗口
                    if w.ProcessId != my_pid:
                        continue
                    tname = w.ControlTypeName
                    if tname in ("MenuControl", "PopupMenuControl", "ToolTipControl"):
                        walk(w, 0)
                    elif tname == "WindowControl" and _popup_like(w):
                        walk(w, 0)
                except Exception:
                    continue
        except Exception:
            pass
        return elements, ctrls, sigs

    def perceive(self) -> dict:
        """感知绑定窗口的可交互控件，返回与 Web 感知同构的状态 dict。"""
        err = self._check_window()
        if err:
            return {"url": "", "title": "", "count": 0, "elements": [], "frames": [], "error": err}
        elements, ctrls, sigs = self._collect()
        self._cache = {}
        seq = 0
        for el, sig in zip(elements, sigs):
            seq += 1
            el["idx"] = seq
            el["frame"] = 0
            self._cache[seq] = sig
        url = f"app://{self.window.Name}"
        return {
            "url": url,
            "title": self.window.Name,
            "count": seq,
            "elements": elements,
            "frames": [{"index": 0, "url": url, "count": seq}] if seq else [],
        }

    def _relocate(self, idx):
        """按编号重定位控件（特征匹配 → 名称包含兜底）。返回 (Control, 错误信息)。"""
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return None, f"非法编号: {idx}"
        sig = self._cache.get(idx)
        if sig is None:
            return None, f"编号 {idx} 不在最近一次感知结果中，请先 perceive_page 刷新"
        elements, ctrls, sigs = self._collect()
        for el, c, s in zip(elements, ctrls, sigs):
            if s == sig:
                return c, ""
        want_tag, want_name = sig[0], sig[1]
        if want_name:
            for el, c, s in zip(elements, ctrls, sigs):
                if s[0][0] == want_tag and want_name in s[0][1]:
                    return c, ""
        return None, f"编号 {idx} 对应元素已失效且无法按特征重定位，请 perceive_page 刷新后重试"

    def _find_by_text(self, text: str):
        """按名称精确/包含查找可交互控件。返回 Control 或 None。"""
        elements, ctrls, _ = self._collect()
        for el, c in zip(elements, ctrls):
            if el["name"] == text:
                return c
        for el, c in zip(elements, ctrls):
            if text in el["name"]:
                return c
        return None

    # ---------- 执行 ----------

    def _click(self, ctrl) -> tuple:
        try:
            r = ctrl.BoundingRectangle
        except Exception:
            return False, "无法获取控件位置（可能已失效）"
        x, y = int((r.left + r.right) / 2), int((r.top + r.bottom) / 2)
        if x <= 0 and y <= 0:
            return False, "控件不可见（坐标异常）"
        try:
            self.window.SetActive()
        except Exception:
            pass
        try:
            auto.Click(x, y, waitTime=0.2)
            return True, f"点击成功({x},{y})"
        except Exception as e:
            return False, f"点击失败: {str(e)[:100]}"

    def act(self, action: str, params: dict) -> tuple:
        """执行桌面动作。返回 (是否成功, 结果说明)。"""
        err = self._check_window()
        if err:
            return False, err.replace("错误：", "")
        try:
            if action == "click":
                c, msg = self._relocate(params.get("idx"))
                if c is None:
                    return False, msg
                return self._click(c)

            if action == "click_text":
                text = str(params.get("text", "")).strip()
                if not text:
                    return False, "click_text 缺少 text 参数"
                c = self._find_by_text(text)
                if c is None:
                    return False, f"未找到名称含「{text}」的可交互控件"
                return self._click(c)

            if action == "type":
                c, msg = self._relocate(params.get("idx"))
                if c is None:
                    return False, msg
                text = str(params.get("text", ""))
                try:
                    self.window.SetActive()
                except Exception:
                    pass
                try:
                    c.GetValuePattern().SetValue(text)
                except Exception:
                    # ValuePattern 不可用（自绘输入框）→ 剪贴板粘贴兜底（中文安全）
                    try:
                        c.SetFocus()
                        auto.SetClipboardText(text)
                        auto.SendKeys("{Ctrl}a{Del}{Ctrl}v", waitTime=0.1)
                    except Exception as e:
                        return False, f"输入失败: {str(e)[:100]}"
                if params.get("press_enter"):
                    auto.SendKeys("{Enter}", waitTime=0.1)
                return True, "输入成功"

            if action == "select":
                c, msg = self._relocate(params.get("idx"))
                if c is None:
                    return False, msg
                value = str(params.get("value", ""))
                try:
                    self.window.SetActive()
                except Exception:
                    pass
                try:
                    c.GetExpandCollapsePattern().Expand()
                except Exception as e:
                    return False, f"展开下拉失败: {str(e)[:80]}"
                time.sleep(0.5)
                # 展开的选项可能在独立 popup，重遍历全局查找
                elements, ctrls, _ = self._collect()
                target = None
                for el, cc in zip(elements, ctrls):
                    if el["tag"] in ("listitem", "comboboxitem", "dataitem") and value in el["name"]:
                        target = cc
                        break
                if target is None:
                    return False, f"下拉展开后未找到选项「{value}」"
                return self._click(target)

            if action == "scroll":
                try:
                    r = self.window.BoundingRectangle
                    auto.MoveTo(int((r.left + r.right) / 2), int((r.top + r.bottom) / 2))
                    if str(params.get("direction", "down")) == "up":
                        auto.WheelUp(waitTime=0.2)
                    else:
                        auto.WheelDown(waitTime=0.2)
                    return True, "滚动成功"
                except Exception as e:
                    return False, f"滚动失败: {str(e)[:80]}"

            if action == "key":
                keys = str(params.get("keys", "")).strip()
                if not keys:
                    return False, "key 缺少 keys 参数（SendKeys 语法，如 \"{Ctrl}s\"）"
                try:
                    self.window.SetActive()
                except Exception:
                    pass
                auto.SendKeys(keys, waitTime=0.2)
                return True, f"按键成功: {keys}"

            if action == "drag":
                src_idx = params.get("from_idx", params.get("idx"))
                c, msg = self._relocate(src_idx)
                if c is None:
                    return False, msg
                try:
                    sr = c.BoundingRectangle
                    sx, sy = int((sr.left + sr.right) / 2), int((sr.top + sr.bottom) / 2)
                except Exception:
                    return False, "无法获取拖拽源位置"
                if params.get("to_idx") is not None:
                    t, msg = self._relocate(params.get("to_idx"))
                    if t is None:
                        return False, msg
                    try:
                        tr = t.BoundingRectangle
                    except Exception:
                        return False, "无法获取拖拽目标位置"
                    tx, ty = int((tr.left + tr.right) / 2), int((tr.top + tr.bottom) / 2)
                else:
                    tx, ty = sx, sy
                try:
                    dx = float(params.get("dx") or 0)
                    dy = float(params.get("dy") or 0)
                except (TypeError, ValueError):
                    return False, "drag 的 dx/dy 必须是数字"
                tx, ty = int(tx + dx), int(ty + dy)
                try:
                    self.window.SetActive()
                except Exception:
                    pass
                try:
                    auto.MoveTo(sx, sy, waitTime=0.1)
                    auto.MouseLeftButtonDown()
                    steps = 10
                    for i in range(1, steps + 1):
                        auto.MoveTo(sx + (tx - sx) * i // steps, sy + (ty - sy) * i // steps, waitTime=0.02)
                    auto.MouseLeftButtonUp()
                    return True, "拖拽成功"
                except Exception as e:
                    try:
                        auto.MouseLeftButtonUp()
                    except Exception:
                        pass
                    return False, f"拖拽失败: {str(e)[:80]}"

            return False, f"桌面模式不支持动作: {action}（支持 click/click_text/type/select/scroll/key/drag）"
        except Exception as e:
            return False, f"执行异常: {str(e)[:120]}"

    # ---------- 截图 ----------

    def screenshot(self, path: Path) -> bool:
        """窗口截图到指定路径。失败返回 False（不阻断探索）。"""
        if self.window is None:
            return False
        try:
            try:
                ok = self.window.CaptureToImage(str(path))
            except TypeError:
                ok = self.window.CaptureToImage(str(path), False)
            return bool(ok)
        except Exception:
            return False
# AI_GENERATE_END -
