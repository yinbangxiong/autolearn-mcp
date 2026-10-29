# AI_GENERATE_START --
# -*- coding: utf-8 -*-
"""记忆沉淀层：情景记忆 → 语义记忆 / 程序记忆。

职责分工（与"AI 助手当大脑"架构一致）：
- 本模块只做确定性工作：解析会话轨迹、生成蒸馏摘要、记忆文件读写与检索；
- 蒸馏推理（把轨迹总结成知识/技能）由调用方大脑完成，通过 save_* 工具写回。

目录结构：
- data/sessions/<ts>/session.jsonl   情景记忆（原始轨迹，只读）
- data/memory/semantic.md            语义记忆（页面/业务知识，人可读可编辑）
- data/memory/skills/<id>.json       程序记忆（参数化操作技能）
- data/memory/index.json             记忆索引（技能清单、已消化会话）
"""

import json
import re
import time
from pathlib import Path

from autolearn.config import DATA_DIR

MEMORY_DIR = DATA_DIR / "memory"
SEMANTIC_FILE = MEMORY_DIR / "semantic.md"
SKILLS_DIR = MEMORY_DIR / "skills"
INDEX_FILE = MEMORY_DIR / "index.json"

_SESSIONS_DIR = DATA_DIR / "sessions"


def _ensure_dirs():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def load_index() -> dict:
    _ensure_dirs()
    if INDEX_FILE.exists():
        with open(INDEX_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"skills": [], "processed_sessions": []}


def _save_index(index: dict):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _load_session(path: Path) -> dict:
    """解析一份 session.jsonl，返回紧凑结构。"""
    goal = ""
    steps = []
    end = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = e.get("type")
            if t == "session_start":
                goal = e.get("goal", "")
            elif t == "step":
                steps.append(e)
            elif t == "session_end":
                end = e
    return {"dir": path.parent.name, "goal": goal, "steps": steps, "end": end}


def build_digest(max_sessions: int = 5):
    """生成未消化会话的蒸馏摘要，返回 (摘要文本, 会话目录名列表)。"""
    index = load_index()
    processed = set(index.get("processed_sessions", []))
    if not _SESSIONS_DIR.exists():
        return "（没有任何探索会话）", []
    dirs = sorted(
        p.name for p in _SESSIONS_DIR.iterdir()
        if p.is_dir() and (p / "session.jsonl").exists()
    )
    pending = [d for d in dirs if d not in processed][-max_sessions:]
    if not pending:
        return "（所有会话均已消化；已处理: " + ", ".join(dirs[-8:]) + "）", []

    blocks = []
    for name in pending:
        s = _load_session(_SESSIONS_DIR / name / "session.jsonl")
        lines = [f"### 会话 {name}", f"目标: {s['goal']}"]
        if s["end"]:
            lines.append(f"结束: {s['end'].get('status', '')} | {str(s['end'].get('summary', ''))[:200]}")
        lines.append("步骤轨迹:")
        for st in s["steps"]:
            el = st.get("element") or {}
            el_desc = f"[{el.get('idx')}]\"{(el.get('name') or '')[:20]}\"" if el else ""
            params = st.get("params") or {}
            p_desc = ""
            if params.get("text"):
                p_desc = f" text={str(params['text'])[:20]}"
            elif params.get("value"):
                p_desc = f" value={params['value']}"
            result = "OK" if st.get("ok") else f"FAIL({str(st.get('result', ''))[:60]})"
            thought = str(st.get("thought") or "")[:60]
            lines.append(
                f"  {st.get('step')}. {st.get('url', '')[:70]} | {st.get('action')}{el_desc}{p_desc} → {result} | {thought}"
            )
        pages = {}
        for st in s["steps"]:
            u = st.get("url", "")
            if u and u not in pages:
                pages[u] = st.get("title", "")
        if pages:
            lines.append("途径页面: " + "; ".join(f"{t}({u})" for u, t in pages.items()))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), pending


def save_semantic(title: str, content: str, source: str = "") -> str:
    """把一段语义知识写入 semantic.md；同名标题节整体替换（即更新）。"""
    _ensure_dirs()
    ts = time.strftime("%Y-%m-%d %H:%M")
    section = f"## {title}\n\n{content.strip()}\n\n> 来源: {source or '探索'} | 更新: {ts}"
    text = SEMANTIC_FILE.read_text(encoding="utf-8") if SEMANTIC_FILE.exists() else "# 系统语义记忆\n"
    pattern = re.compile(rf"## {re.escape(title)}\n.*?(?=\n## |\Z)", re.S)
    if pattern.search(text):
        text = pattern.sub(section, text)
    else:
        text = text.rstrip("\n") + "\n\n" + section
    SEMANTIC_FILE.write_text(text, encoding="utf-8")
    return str(SEMANTIC_FILE)


def save_skill(name: str, description: str, steps: list, source: str = "") -> str:
    """保存参数化操作技能（步骤用文本定位，不依赖易漂移的临时编号）。"""
    _ensure_dirs()
    slug = re.sub(r"\s+", "_", name)[:40] or f"skill_{int(time.time())}"
    skill = {
        "id": slug,
        "name": name,
        "description": description,
        "steps": steps,
        "source_sessions": [s.strip() for s in source.split(",") if s.strip()],
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
        "verified": 0,
    }
    path = SKILLS_DIR / f"{slug}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(skill, f, ensure_ascii=False, indent=2)
    index = load_index()
    entry = {"id": slug, "name": name, "description": description}
    index["skills"] = [s for s in index.get("skills", []) if s["id"] != slug] + [entry]
    _save_index(index)
    return str(path)


def mark_processed(session_names: list) -> int:
    """把会话标记为已消化，返回新增数量。"""
    index = load_index()
    processed = set(index.get("processed_sessions", []))
    new = [n for n in session_names if n and n not in processed]
    index["processed_sessions"] = sorted(processed | set(new))
    _save_index(index)
    return len(new)


def _find_skill_path(skill_id: str):
    """按 id 或名称（精确/包含）定位技能文件，返回 (meta, path) 或 (None, None)。"""
    index = load_index()
    candidates = index.get("skills", [])
    meta = None
    for s in candidates:
        if s["id"] == skill_id or s["name"] == skill_id:
            meta = s
            break
    if meta is None:
        for s in candidates:
            if skill_id.lower() in s["name"].lower():
                meta = s
                break
    if meta is None:
        return None, None
    path = SKILLS_DIR / f"{meta['id']}.json"
    if not path.exists():
        return None, None
    return meta, path


def load_skill(skill_id: str):
    """按 id 或名称加载技能（返回完整技能 dict），找不到返回 None。"""
    _ensure_dirs()
    _, path = _find_skill_path(skill_id)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def record_skill_verification(skill_id: str, ok: bool, detail: str = "") -> str:
    """记录技能回放结果：成功 verified+1，失败写入 history（保留最近 20 条）。"""
    _ensure_dirs()
    _, path = _find_skill_path(skill_id)
    if path is None:
        return ""
    with open(path, encoding="utf-8") as f:
        sk = json.load(f)
    if ok:
        sk["verified"] = int(sk.get("verified", 0)) + 1
    sk.setdefault("history", []).append(
        {"ts": time.strftime("%Y-%m-%d %H:%M"), "ok": ok, "detail": detail[:200]}
    )
    sk["history"] = sk["history"][-20:]
    sk["last_verified_at"] = time.strftime("%Y-%m-%d %H:%M")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sk, f, ensure_ascii=False, indent=2)
    return str(path)


def recall(query: str = "") -> str:
    """检索记忆：技能 + 语义记忆分节。query 为空返回总览。"""
    _ensure_dirs()
    parts = []
    index = load_index()
    skills = index.get("skills", [])
    matched_skills = [
        s for s in skills
        if not query or query.lower() in (s["name"] + s["description"]).lower()
    ]
    if skills:
        parts.append("【程序记忆（可复用操作技能）】")
        if matched_skills:
            for s in matched_skills:
                detail = ""
                path = SKILLS_DIR / f"{s['id']}.json"
                if path.exists():
                    with open(path, encoding="utf-8") as f:
                        sk = json.load(f)
                    step_desc = " → ".join(
                        f"{st.get('action')}:{st.get('text') or ''}" for st in sk.get("steps", [])
                    )
                    detail = f"\n  步骤: {step_desc}"
                parts.append(f"- {s['name']}: {s['description']}{detail}")
        else:
            parts.append(f"（无匹配「{query}」的技能）")
    if SEMANTIC_FILE.exists():
        text = SEMANTIC_FILE.read_text(encoding="utf-8")
        sections = re.split(r"\n(?=## )", text)
        hits = [
            "\n".join(sec.splitlines()[:40])
            for sec in sections
            if sec.startswith("## ") and (not query or query.lower() in sec.lower())
        ]
        if skills:
            parts.append("")
        parts.append("【语义记忆（页面/业务知识）】")
        if hits:
            parts.extend(hits[:6])
        else:
            parts.append(f"（无匹配「{query}」的知识节）")
    if not parts:
        return "（记忆库为空）"
    return "\n".join(parts)
# AI_GENERATE_END --

