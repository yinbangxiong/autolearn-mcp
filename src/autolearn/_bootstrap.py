# AI_GENERATE_START -
# -*- coding: utf-8 -*-
"""首次运行自检：确保 Chromium 内核可用。

用法：
  autolearn-install        # 检测并按需下载 Chromium（约 200MB，仅需一次）
"""

import os
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


def install_browser() -> int:
    if chromium_installed():
        print("Chromium 已就绪", file=sys.stderr)
        return 0
    print("首次使用：正在下载 Chromium 内核（约 200MB，仅需一次）...", file=sys.stderr)
    return subprocess.call(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        env=os.environ.copy(),
    )


def main() -> int:
    code = install_browser()
    if code == 0:
        print("完成。现在可以在 AI 工具里配置并使用 autolearn-mcp 了。", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
# AI_GENERATE_END -
