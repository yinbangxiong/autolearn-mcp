# AI_GENERATE_START -
# -*- coding: utf-8 -*-
"""系统档案层：让 autolearn 支持同时学习多个系统/网站。

目录结构（在 ~/.autolearn/ 下）：
- data/systems/<slug>/profile.json   系统档案（名称/URL/描述/类型）
- data/systems/<slug>/state.json     该系统浏览器登录态（Cookie/Storage）
- data/systems/<slug>/memory/        该系统三层记忆（semantic.md / skills/ / index.json）
- data/systems/_global/memory/       跨系统通用记忆（任何系统都可读写/回放）
- data/credentials.json              各系统登录凭据 {"slug": {"username":..., "password":...}}
- data/last_system                   最后打开的系统 slug（open_system 无参时使用）
- data/sessions/<slug>/<ts>/         情景记忆按系统归档；旧版 sessions/<ts>/ 兼容读取

登录策略（auto_login）：
1. 通用策略链（凭据来自 credentials.json 或 .env 的 AUTO_USERNAME/AUTO_PASSWORD）；
2. 失败则回放该系统的 login 技能（首次人工登录后蒸馏沉淀，slug 固定为 "login"）；
3. 仍失败转人工登录。
"""

import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from autolearn.config import AUTO_PASSWORD, AUTO_USERNAME, DATA_DIR, TARGET_URL

SYSTEMS_DIR = DATA_DIR / "systems"
GLOBAL_SYSTEM = "_global"  # 跨系统通用记忆的保留目录名
CREDENTIALS_FILE = DATA_DIR / "credentials.json"
LAST_SYSTEM_FILE = DATA_DIR / "last_system"
LOGIN_SKILL_ID = "login"  # 登录技能的固定 slug

# Windows 目录名非法字符 + 空白，统一替换为下划线
_SLUG_BAD = re.compile(r'[\\/:*?"<>|\s]+')


def slugify(name: str) -> str:
    """系统名转目录 slug：保留中文/字母/数字，替换非法字符。"""
    slug = _SLUG_BAD.sub("_", (name or "").strip()).strip("_")
    if slug.startswith("."):
        slug = "_" + slug[1:]
    return slug or "default"


def system_dir(slug: str) -> Path:
    return SYSTEMS_DIR / slug


def system_state_file(slug: str) -> Path:
    """该系统的浏览器登录态文件路径。"""
    return system_dir(slug) / "state.json"


def system_memory_dir(slug: str) -> Path:
    """该系统的记忆目录（semantic.md / skills/ / index.json 所在层）。"""
    return system_dir(slug) / "memory"


def _profile_path(slug: str) -> Path:
    return system_dir(slug) / "profile.json"


def get_profile(slug: str) -> dict | None:
    """读取系统档案，不存在返回 None。"""
    p = _profile_path(slug)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def register_system(name: str, url: str = "", description: str = "", kind: str = "web") -> dict:
    """注册/更新系统档案。name 相同且已存在则仅更新 url/description。"""
    slug = slugify(name)
    profile = get_profile(slug) or {
        "slug": slug,
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    if url:
        profile["url"] = url
    profile.setdefault("name", name.strip())
    if description:
        profile["description"] = description
    profile["kind"] = kind  # 预留：web / desktop / mobile（当前仅实现 web）
    p = _profile_path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return profile


def slug_from_url(url: str) -> str:
    """从 URL 生成默认 slug：host[:port]/首段路径，如 zfs_ztessc_cn_fms。

    桌面应用地址 app://窗口标题 → app_窗口标题。
    """
    if (url or "").lower().startswith("app://"):
        body = url[6:].strip("/").strip()
        return slugify("app_" + body) if body else "app_default"
    try:
        u = urlparse(url if "://" in url else "http://" + url)
        parts = [u.netloc.replace(":", "_")]
        seg = (u.path or "").strip("/").split("/")[0]
        if seg and seg.lower() not in ("login", "index", "home"):
            parts.append(seg)
        slug = slugify("_".join(p for p in parts if p))
        return slug or "default"
    except Exception:
        return "default"


def set_last_system(slug: str):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LAST_SYSTEM_FILE.write_text(slug, encoding="utf-8")
    except OSError:
        pass


def get_last_system() -> str:
    try:
        return LAST_SYSTEM_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def resolve_system(name: str = "", url: str = "") -> tuple[str | None, str, str]:
    """解析目标系统，返回 (slug, 打开地址, 错误信息)。

    优先级：
    - system 参数给了：查档案；档案存在 → 用档案 url（显式传 url 时优先传入 url）
    - 仅传 url：按 url 自动注册系统（slug 取自域名），返回该 slug
    - 都没传：last_system → TARGET_URL 兜底
    """
    if name.strip():
        slug = slugify(name)
        profile = get_profile(slug)
        if profile is None:
            return None, "", f"未注册系统「{name}」。可先调用 list_systems 查看已注册系统，或改传 url 自动注册。"
        target = url.strip() or profile.get("url", "")
        if not target:
            return None, "", f"系统「{slug}」档案未配置 url，且本次未传入 url。"
        return slug, target, ""
    if url.strip():
        slug = slug_from_url(url)
        if get_profile(slug) is None:
            register_system(
                slug, url=url,
                description="由 open_system(url) 自动注册",
                kind="desktop" if url.lower().startswith("app://") else "web",
            )
        return slug, url.strip(), ""
    last = get_last_system()
    if last and get_profile(last) is not None:
        profile = get_profile(last)
        if profile.get("url"):
            return last, profile["url"], ""
    if TARGET_URL:
        slug = slug_from_url(TARGET_URL)
        if get_profile(slug) is None:
            register_system(slug, url=TARGET_URL, description="由 TARGET_URL 自动注册")
        return slug, TARGET_URL, ""
    return None, "", "未指定系统：请传 system（已注册系统名）或 url（任意网址），或在 .env 配置 TARGET_URL。"


def list_systems() -> list[dict]:
    """列出所有已注册系统及其记忆概况。"""
    result = []
    if not SYSTEMS_DIR.exists():
        return result
    for d in sorted(SYSTEMS_DIR.iterdir()):
        if not d.is_dir():
            continue
        profile = get_profile(d.name) or {"slug": d.name, "name": d.name}
        mem = d / "memory"
        skills = mem / "skills"
        semantic = mem / "semantic.md"
        n_skills = len([p for p in skills.glob("*.json")]) if skills.exists() else 0
        n_sections = 0
        if semantic.exists():
            try:
                n_sections = len(re.findall(r"^## ", semantic.read_text(encoding="utf-8"), re.M))
            except OSError:
                n_sections = 0
        result.append(
            {
                "slug": d.name,
                "name": profile.get("name", d.name),
                "url": profile.get("url", ""),
                "description": profile.get("description", ""),
                "kind": profile.get("kind", "web"),
                "skills": n_skills,
                "semantic_sections": n_sections,
                "has_login_state": (d / "state.json").exists(),
            }
        )
    return result


def get_credentials(slug: str) -> dict | None:
    """取系统登录凭据：credentials.json 按系统优先，回退 .env 全局凭据。"""
    if CREDENTIALS_FILE.exists():
        try:
            with open(CREDENTIALS_FILE, encoding="utf-8") as f:
                c = (json.load(f) or {}).get(slug) or {}
            if c.get("username") and c.get("password"):
                return {"username": str(c["username"]), "password": str(c["password"])}
        except (json.JSONDecodeError, OSError):
            pass
    if AUTO_USERNAME and AUTO_PASSWORD:
        return {"username": AUTO_USERNAME, "password": AUTO_PASSWORD}
    return None


def _default_slug() -> str:
    if TARGET_URL:
        return slug_from_url(TARGET_URL)
    return "default"


def migrate_legacy() -> str:
    """旧版单系统布局一次性迁移到按系统归档（幂等，迁移后旧位置不再存在）。

    旧布局：data/state.json、data/memory/、data/sessions/<ts>/
    新布局：data/systems/<slug>/{state.json, memory/}、data/sessions/<slug>/<ts>/
    旧技能 JSON 会补写 system 字段（归属默认系统）。
    """
    legacy_state = DATA_DIR / "state.json"
    legacy_memory = DATA_DIR / "memory"
    legacy_sessions = DATA_DIR / "sessions"
    has_legacy_sessions = False
    if legacy_sessions.exists():
        has_legacy_sessions = any(
            p.is_dir() and (p / "session.jsonl").exists() for p in legacy_sessions.iterdir()
        )
    if not (legacy_state.exists() or legacy_memory.exists() or has_legacy_sessions):
        return ""

    slug = get_last_system() or _default_slug()
    dest = system_dir(slug)
    dest.mkdir(parents=True, exist_ok=True)
    moved = []

    if legacy_state.exists():
        shutil.move(str(legacy_state), str(dest / "state.json"))
        moved.append("state.json")

    if legacy_memory.exists():
        mem_dest = dest / "memory"
        mem_dest.mkdir(exist_ok=True)
        for item in legacy_memory.iterdir():
            target = mem_dest / item.name
            if target.exists():
                if item.is_dir():
                    for sub in item.iterdir():
                        if not (target / sub.name).exists():
                            shutil.move(str(sub), str(target / sub.name))
                # 同名冲突时保留新位置内容（旧文件视为过期）
                continue
            shutil.move(str(item), str(target))
        shutil.rmtree(legacy_memory, ignore_errors=True)
        moved.append("memory/")

    # 旧技能补 system 字段（save_skill 新写入的都自带）
    skills_dir = dest / "memory" / "skills"
    if skills_dir.exists():
        for sp in skills_dir.glob("*.json"):
            try:
                with open(sp, encoding="utf-8") as f:
                    sk = json.load(f)
                if not sk.get("system"):
                    sk["system"] = slug
                    with open(sp, "w", encoding="utf-8") as f:
                        json.dump(sk, f, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, OSError):
                continue

    if legacy_sessions.exists():
        for d in legacy_sessions.iterdir():
            if d.is_dir() and (d / "session.jsonl").exists():
                target = legacy_sessions / slug / d.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.move(str(d), str(target))
        moved.append("sessions/")

    if moved:
        set_last_system(slug)
        return f"已将旧版单系统数据迁移到 systems/{slug}/（{', '.join(moved)}）"
    return ""
# AI_GENERATE_END -
