# AI_GENERATE_START -
# -*- coding: utf-8 -*-
"""全局配置：环境变量优先，其次 ~/.autolearn/.env，供各模块共用。"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 应用根目录（可用 AUTOLEARN_HOME 覆盖）。数据与配置都放用户目录，升级/重装代码不丢记忆。
APP_DIR = Path(os.getenv("AUTOLEARN_HOME", str(Path.home() / ".autolearn")))
DATA_DIR = APP_DIR / "data"

# Chromium 内核安装在该目录，避免依赖全局安装位置
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(APP_DIR / "browsers"))

APP_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(APP_DIR / ".env")

# 目标系统地址（建议填测试环境）
TARGET_URL = os.getenv("TARGET_URL", "")

# 自动登录凭据（auto_login 工具使用；留空则只能人工登录）
AUTO_USERNAME = os.getenv("AUTO_USERNAME", "")
AUTO_PASSWORD = os.getenv("AUTO_PASSWORD", "")

# LLM 配置（任意 OpenAI 兼容接口：DeepSeek / GLM / Qwen / OpenAI 等，仅 CLI 直连模式需要）
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# 运行参数
MAX_STEPS = int(os.getenv("MAX_STEPS", "30"))  # 单次探索最大步数
HISTORY_STEPS = int(os.getenv("HISTORY_STEPS", "6"))  # 注入 prompt 的历史步骤数
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
CAPTURE_SCREENSHOTS = os.getenv("CAPTURE_SCREENSHOTS", "true").lower() == "true"
# AI_GENERATE_END -
