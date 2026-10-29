# AI_GENERATE_START -
# -*- coding: utf-8 -*-
"""情景记忆记录器：每个会话一个目录，逐步写入 JSONL，可选逐步截图。"""

import json
import time
from pathlib import Path

from autolearn.config import DATA_DIR


class SessionRecorder:
    """一次探索会话 = data/sessions/<时间戳>/ 下的 session.jsonl + shots/ 截图。"""

    def __init__(self, goal: str):
        self.dir: Path = DATA_DIR / "sessions" / time.strftime("%Y%m%d_%H%M%S")
        (self.dir / "shots").mkdir(parents=True, exist_ok=True)
        self.file: Path = self.dir / "session.jsonl"
        self.record("session_start", goal=goal)

    def record(self, type_: str, **fields):
        """追加一条记忆事件（JSONL，UTF-8）。"""
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "type": type_, **fields}
        with open(self.file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def screenshot(self, page, step: int):
        """截取当前页面，返回相对路径；失败返回 None（不阻断探索）。"""
        rel = f"shots/step_{step:04d}.png"
        try:
            page.screenshot(path=str(self.dir / rel))
            return rel
        except Exception:
            return None

    @property
    def session_dir(self) -> str:
        return str(self.dir)
# AI_GENERATE_END -

