# AI_GENERATE_START --
# -*- coding: utf-8 -*-
"""首次运行自检：确保浏览器内核可用（优先复用系统 Chrome/Edge）。

用法：
  autolearn-install        # 检测并按需准备浏览器（有系统 Chrome/Edge 则免下载）
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def chromium_installed() -> bool:
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not root.exists():
        return False
    for d in root.glob("chromium-*"):
        if (d / "INSTALLATION_COMPLETE").exists():
            return True
    return False


def find_system_channel() -> str | None:
    """探测系统 Chrome/Edge，返回 Playwright channel 名；找不到返回 None。

    覆盖 PATH 与 Windows 常见安装路径；其他平台靠 launch_chromium 的
    失败回退链兜底，探测结果仅用于决定是否需要下载内核。
    """
    for cmd in ("chrome", "google-chrome", "msedge"):
        if shutil.which(cmd):
            return "msedge" if "edge" in cmd else "chrome"
    pf = os.environ.get("ProgramFiles", "")
    pf86 = os.environ.get("ProgramFiles(x86)", "")
    local = os.environ.get("LocalAppData", "")
    for path, channel in (
        (rf"{pf}\Google\Chrome\Application\chrome.exe", "chrome"),
        (rf"{pf86}\Google\Chrome\Application\chrome.exe", "chrome"),
        (rf"{local}\Google\Chrome\Application\chrome.exe", "chrome"),
        (rf"{pf}\Microsoft\Edge\Application\msedge.exe", "msedge"),
        (rf"{pf86}\Microsoft\Edge\Application\msedge.exe", "msedge"),
    ):
        if path and Path(path).exists():
            return channel
    return None


def install_browser() -> int:
    if chromium_installed():
        print("Chromium 已就绪", file=sys.stderr)
        return 0
    if find_system_channel():
        print("检测到系统 Chrome/Edge，将直接复用，无需下载内核", file=sys.stderr)
        return 0
    print("未检测到系统 Chrome/Edge，开始下载 Chromium 内核（约 200MB，仅需一次）...", file=sys.stderr)
    return subprocess.call(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        env=os.environ.copy(),
    )


async def launch_chromium(pw, headless: bool):
    """统一浏览器启动策略：优先系统 Chrome，再 Edge，最后回退内置 Chromium。

    企业 Chrome 被策略禁自动化时自动落到 Edge（Windows 必有），再不行
    回退 Playwright 内置内核；全部失败时异常上抛（与原行为一致）。
    """
    for channel in ("chrome", "msedge"):
        try:
            return await pw.chromium.launch(headless=headless, channel=channel)
        except Exception:
            continue
    return await pw.chromium.launch(headless=headless)


def main() -> int:
    code = install_browser()
    if code == 0:
        print("完成。现在可以在 AI 工具里配置并使用 autolearn-mcp 了。", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
# AI_GENERATE_END --
