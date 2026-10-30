# AI_GENERATE_START ---
# -*- coding: utf-8 -*-
"""记忆沉淀层：情景记忆 → 语义记忆 / 程序记忆（按系统归档）。

职责分工（与"AI 助手当大脑"架构一致）：
- 本模块只做确定性工作：解析会话轨迹、生成蒸馏摘要、记忆文件读写与检索；
- 蒸馏推理（把轨迹总结成知识/技能）由调用方大脑完成，通过 save_* 工具写回。

目录结构（~/.autolearn/ 下，记忆按系统隔离）：
- data/systems/<slug>/memory/semantic.md      该系统语义记忆（人可读可编辑）
- data/systems/<slug>/memory/skills/<id>.json 该系统程序记忆（参数化操作技能）
- data/systems/<slug>/memory/index.json       该系统记忆索引
- data/systems/_global/memory/                跨系统通用记忆（system="_global"）
- data/sessions/<slug>/<ts>/session.jsonl     情景记忆（原始轨迹，只读）
- data/sessions/<ts>/session.jsonl            旧版会话（兼容读取，归属默认系统）
"""

import json
import re
import time
from pathlib import Path

from autolearn.config import DATA_DIR
from autolearn.systems import GLOBAL_SYSTEM, SYSTEMS_DIR, list_systems, system_memory_dir

_SESSIONS_DIR = DATA_DIR / "sessions"


def _mem_root(system: str = "") -> Path:
    """某系统的记忆根目录；空串 = 跨系统通用记忆（_global）。"""
    return system_memory_dir(system or GLOBAL_SYSTEM)


def _skills_dir(system: str = "") -> Path:
    return _mem_root(system) / "skills"


def _index_file(system: str = "") -> Path:
    return _mem_root(system) / "index.json"


def _semantic_file(system: str = "") -> Path:
    return _mem_root(system) / "semantic.md"


def _ensure_dirs(system: str = ""):
    _skills_dir(system).mkdir(parents=True, exist_ok=True)


def load_index(system: str = "") -> dict:
    _ensure_dirs(system)
    f = _index_file(system)
    if f.exists():
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError:
            pass
    return {"skills": [], "processed_sessions": []}


def _save_index(index: dict, system: str = ""):
    _ensure_dirs(system)
    with open(_index_file(system), "w", encoding="utf-8") as f:
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


def _session_dirs(system: str) -> list[str]:
    """列出某系统的全部会话目录名，按时间排序。

    布局 data/sessions/<slug>/<ts>/；旧版平铺 data/sessions/<ts>/ 由
    systems.migrate_legacy() 在服务启动时统一搬入默认系统目录。
    """
    d = _SESSIONS_DIR / system
    if not d.is_dir():
        return []
    return sorted(
        p.name for p in d.iterdir() if p.is_dir() and (p / "session.jsonl").exists()
    )


def _session_path(system: str, name: str) -> Path | None:
    """按系统+目录名定位 session.jsonl。"""
    p = _SESSIONS_DIR / system / name / "session.jsonl"
    return p if p.exists() else None


def build_digest(system: str = "", max_sessions: int = 5):
    """生成某系统未消化会话的蒸馏摘要，返回 (摘要文本, 会话目录名列表)。

    system 为空 = 跨系统通用记忆（_global，通常不会产生会话，仅作兜底）。
    """
    index = load_index(system)
    processed = set(index.get("processed_sessions", []))
    dirs = _session_dirs(system or GLOBAL_SYSTEM)
    if not dirs:
        return "（没有任何探索会话）", []
    pending = [d for d in dirs if d not in processed][-max_sessions:]
    if not pending:
        return "（所有会话均已消化；已处理: " + ", ".join(dirs[-8:]) + "）", []

    blocks = []
    for name in pending:
        path = _session_path(system, name)
        if path is None:
            continue
        s = _load_session(path)
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


def save_semantic(title: str, content: str, source: str = "", system: str = "") -> str:
    """把一段语义知识写入该系统 semantic.md；同名标题节整体替换（即更新）。

    system 为空 = 跨系统通用记忆（_global）。
    """
    system = system or GLOBAL_SYSTEM
    _ensure_dirs(system)
    ts = time.strftime("%Y-%m-%d %H:%M")
    section = f"## {title}\n\n{content.strip()}\n\n> 来源: {source or '探索'} | 更新: {ts}"
    sem = _semantic_file(system)
    text = sem.read_text(encoding="utf-8") if sem.exists() else "# 系统语义记忆\n"
    pattern = re.compile(rf"## {re.escape(title)}\n.*?(?=\n## |\Z)", re.S)
    if pattern.search(text):
        text = pattern.sub(section, text)
    else:
        text = text.rstrip("\n") + "\n\n" + section
    sem.write_text(text, encoding="utf-8")
    return str(sem)


def save_skill(name: str, description: str, steps: list, source: str = "", system: str = "") -> str:
    """保存参数化操作技能（步骤用文本定位，不依赖易漂移的临时编号）。

    system 为空 = 跨系统通用技能（_global，任何系统均可回放）；
    归属某系统的技能仅在该系统回放（run_skill 归属校验）。
    """
    system = system or GLOBAL_SYSTEM
    _ensure_dirs(system)
    slug = re.sub(r"\s+", "_", name)[:40] or f"skill_{int(time.time())}"
    skill = {
        "id": slug,
        "name": name,
        "description": description,
        "system": system,
        "steps": steps,
        "source_sessions": [s.strip() for s in source.split(",") if s.strip()],
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
        "verified": 0,
    }
    path = _skills_dir(system) / f"{slug}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(skill, f, ensure_ascii=False, indent=2)
    index = load_index(system)
    entry = {"id": slug, "name": name, "description": description}
    index["skills"] = [s for s in index.get("skills", []) if s["id"] != slug] + [entry]
    _save_index(index, system)
    return str(path)


def mark_processed(session_names: list) -> int:
    """把会话标记为已消化，返回新增数量。

    扫描所有系统目录逐个匹配（不同系统可能存在同名时间戳目录，需分别标记）。
    """
    wanted = {n.strip() for n in session_names if n and n.strip()}
    if not wanted or not _SESSIONS_DIR.exists():
        return 0
    new_count = 0
    for d in _SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        for name in wanted:
            if (d / name / "session.jsonl").exists():
                index = load_index(d.name)
                processed = set(index.get("processed_sessions", []))
                if name not in processed:
                    index["processed_sessions"] = sorted(processed | {name})
                    _save_index(index, d.name)
                    new_count += 1
    return new_count


def _find_skill_path(skill_id: str, system: str = ""):
    """按 id 或名称（精确/包含）在指定系统定位技能文件，返回 (meta, path) 或 (None, None)。"""
    index = load_index(system)
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
    path = _skills_dir(system) / f"{meta['id']}.json"
    if not path.exists():
        return None, None
    return meta, path


def load_skill(skill_id: str, system: str = ""):
    """按 id 或名称加载技能。优先查指定系统，未指定/找不到时查通用记忆（_global）。

    返回完整技能 dict（含 system 字段），找不到返回 None。
    """
    _ensure_dirs(system or GLOBAL_SYSTEM)
    if system:
        _, path = _find_skill_path(skill_id, system)
        if path is not None:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    _, path = _find_skill_path(skill_id, GLOBAL_SYSTEM)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def record_skill_verification(skill_id: str, ok: bool, detail: str = "", system: str = "") -> str:
    """记录技能回放结果：成功 verified+1，失败写入 history（保留最近 20 条）。"""
    system = system or GLOBAL_SYSTEM
    _ensure_dirs(system)
    _, path = _find_skill_path(skill_id, system)
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


def _overview_all() -> str:
    """跨系统记忆总览：各系统技能数与知识节数。"""
    lines = ["【跨系统记忆总览】"]
    systems = [s for s in list_systems() if s["slug"] != GLOBAL_SYSTEM]
    if not systems:
        lines.append("（尚无已注册系统。调用 open_system(url) 探索后自动注册）")
    for s in systems:
        lines.append(
            f"- {s['name']}({s['slug']}): 技能 {s['skills']} 个, 知识节 {s['semantic_sections']} 个"
            f" | {s['url']}"
        )
    glob = SYSTEMS_DIR / GLOBAL_SYSTEM / "memory"
    if glob.exists():
        lines.append("- _global: 跨系统通用记忆（recall(query, system=\"_global\") 查看详情）")
    lines.append("\n提示：传 system 参数查看指定系统详情，如 recall(query=\"报销\", system=\"zfs\")")
    return "\n".join(lines)


def _has_hits(text: str) -> bool:
    """判断单系统 recall 结果里是否真的命中内容（而非仅有"无匹配"提示）。"""
    if not text or "（记忆库为空）" in text:
        return False
    lines = [l for l in text.splitlines() if l.strip()]
    if any(l.startswith("- ") for l in lines):
        return True
    return any(
        l for l in lines
        if not l.startswith("【") and not l.startswith("（无匹配") and not l.startswith(">")
    )


def recall_all(query: str = "") -> str:
    """跨系统检索：遍历所有已注册系统 + 通用记忆，返回各系统命中结果。"""
    parts = []
    slugs = [s["slug"] for s in list_systems() if s["slug"] != GLOBAL_SYSTEM]
    if GLOBAL_SYSTEM not in slugs:
        slugs.append(GLOBAL_SYSTEM)
    for slug in slugs:
        r = recall(query, system=slug, include_global=False)
        if _has_hits(r):
            parts.append(f"=== {slug} ===\n{r}")
    return "\n\n".join(parts) if parts else f"（所有系统均无匹配「{query}」的记忆）"


def recall(query: str = "", system: str = "", include_global: bool = True) -> str:
    """检索记忆：技能 + 语义记忆分节。

    system 给了 → 检索该系统（默认附带 _global 通用记忆）；
    system 与 query 都空 → 返回跨系统总览。
    """
    if not system and not query:
        return _overview_all()
    system = system or GLOBAL_SYSTEM
    _ensure_dirs(system)
    parts = []
    index = load_index(system)
    skills = index.get("skills", [])
    matched_skills = [
        s for s in skills
        if not query or query.lower() in (s["name"] + s["description"]).lower()
    ]
    label = "（通用）" if system == GLOBAL_SYSTEM else f"（{system}）"
    if skills:
        parts.append(f"【程序记忆（可复用操作技能）{label}】")
        if matched_skills:
            for s in matched_skills:
                detail = ""
                path = _skills_dir(system) / f"{s['id']}.json"
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
    sem = _semantic_file(system)
    if sem.exists():
        text = sem.read_text(encoding="utf-8")
        sections = re.split(r"\n(?=## )", text)
        hits = [
            "\n".join(sec.splitlines()[:40])
            for sec in sections
            if sec.startswith("## ") and (not query or query.lower() in sec.lower())
        ]
        if skills:
            parts.append("")
        parts.append(f"【语义记忆（页面/业务知识）{label}】")
        if hits:
            parts.extend(hits[:6])
        else:
            parts.append(f"（无匹配「{query}」的知识节）")
    if include_global and system != GLOBAL_SYSTEM:
        glob = recall(query, system=GLOBAL_SYSTEM, include_global=False)
        if "（记忆库为空）" not in glob and "（无匹配" not in glob:
            parts.append("\n" + glob)
    if not parts:
        return "（记忆库为空）"
    return "\n".join(parts)
# AI_GENERATE_END ---
