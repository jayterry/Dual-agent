"""
可註冊的桌面技能（類似 OpenClaw 的 skill 概念）：以名稱與參數呼叫本機能力。
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import textwrap
import webbrowser
from typing import Any
from urllib.parse import quote_plus, urlparse

from dual_agent.skill_types import RiskLevel, SkillContext, SkillResult, SkillSpec

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
# CAI：`cai/skills`；DAI：`dai/skills`。兩代理分目錄，Planner/Executor 共用同一註冊表。
_SKILLS_DIRS: tuple[str, ...] = (
    os.path.join(_ROOT_DIR, "cai", "skills"),
    os.path.join(_ROOT_DIR, "dai", "skills"),
)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_frontmatter(md_text: str) -> dict[str, Any]:
    """
    只解析最前面的 YAML frontmatter（--- ... ---）。
    目標：不新增依賴（如 pyyaml），但足以讀 name/description/risk_level/requires_confirmation。

    允許的簡化語法：
    - key: value
    - aliases: [a, b] 或 aliases: a,b
    """
    src = md_text.lstrip("\ufeff")
    if not src.startswith("---"):
        return {}
    lines = src.splitlines()
    if len(lines) < 3:
        return {}
    # 找到第二個 ---
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    block = lines[1:end]
    out: dict[str, Any] = {}
    for raw in block:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if ":" not in raw:
            continue
        k, v = raw.split(":", 1)
        key = k.strip()
        val = v.strip()
        if not key:
            continue
        # very small coercions
        low = val.lower()
        if low in ("true", "false"):
            out[key] = (low == "true")
            continue
        if key == "aliases":
            s = val.strip()
            if s.startswith("[") and s.endswith("]"):
                inner = s[1:-1].strip()
                items = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
                out[key] = items
            else:
                items = [x.strip().strip("'\"") for x in s.split(",") if x.strip()]
                out[key] = items
            continue
        out[key] = val.strip().strip("'\"")
    return out


def _load_handler_from_path(skill_name: str, handler_path: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"skills.{skill_name}.handler", handler_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load handler from {handler_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[call-arg]
    return mod


def _load_skill_specs_from_dirs() -> dict[str, SkillSpec]:
    """
    啟動時：掃描 cai/skills 與 dai/skills，載入各 skill 的 metadata + handler。
    SKILL.md 正文可再按需讀取（progressive disclosure）。
    同名 skill 重複時拋錯，避免靜默覆寫。
    """
    skills: dict[str, SkillSpec] = {}
    for base in _SKILLS_DIRS:
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            skill_dir = os.path.join(base, entry)
            if not os.path.isdir(skill_dir):
                continue
            md_path = os.path.join(skill_dir, "SKILL.md")
            handler_path = os.path.join(skill_dir, "handler.py")
            if not os.path.isfile(md_path) or not os.path.isfile(handler_path):
                continue

            meta = _parse_frontmatter(_read_text(md_path))
            name = str(meta.get("name") or entry).strip()
            desc = str(meta.get("description") or "").strip()
            if not name or not desc:
                continue
            if name in skills:
                raise ValueError(
                    f"重複的 skill 名稱 {name!r}：已於其他目錄註冊，請更名。衝突路徑 {skill_dir}"
                )

            risk = str(meta.get("risk_level") or "low").strip().lower()
            if risk not in ("low", "medium", "high", "critical"):
                risk = "low"
            requires_conf = bool(meta.get("requires_confirmation") or False)
            aliases = meta.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []

            mod = _load_handler_from_path(name, handler_path)
            handle = getattr(mod, "handle", None)
            if not callable(handle):
                raise TypeError(f"{handler_path} must export callable handle(args, ctx)")
            args_schema = getattr(mod, "ARGS_SCHEMA", {}) or {}
            if not isinstance(args_schema, dict):
                args_schema = {}

            skills[name] = SkillSpec(
                name=name,
                description=desc,
                handler=handle,
                aliases=[str(a) for a in aliases if str(a).strip()],
                risk_level=risk,  # type: ignore[arg-type]
                requires_confirmation=requires_conf,
                args_schema=args_schema,
                skill_dir=skill_dir,
            )
    return skills

def _is_safe_http_url(url: str) -> bool:
    u = url.strip()
    parsed = urlparse(u)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc or u.startswith("http"))

_SITE_ALIASES: dict[str, str] = {
    "github": "https://github.com/",
    "github.com": "https://github.com/",
    "youtube": "https://www.youtube.com/",
    "youtube.com": "https://www.youtube.com/",
    "www.youtube.com": "https://www.youtube.com/",
}


def resolve_site_or_url(raw: str) -> str:
    """
    允許用網站別名（如 github）取代完整 URL。
    只回傳 http/https URL；解析不到就回傳原字串（由上層再判斷是否允許）。
    """
    t = (raw or "").strip()
    if not t:
        return ""
    key = t.lower()
    mapped = _SITE_ALIASES.get(key, t)
    mapped = (mapped or "").strip()
    if not mapped:
        return ""
    # 裸網域/host（例如 youtube.com）自動補 https://
    parsed = urlparse(mapped)
    if not parsed.scheme and "." in mapped and " " not in mapped and not mapped.startswith("//"):
        return f"https://{mapped}"
    return mapped


def _deprecated_inline_skill_implementations_notice() -> str:
    return textwrap.dedent(
        """
        舊版 skills_registry.py 內建的 skill_open_url/skill_search_web/skill_open_app 已改為資料夾型 skills。
        若你看到此訊息，表示 cai/skills 或 dai/skills 缺少對應 skill 資料夾或載入失敗。
        """
    ).strip()


def _resolve_windows_app(name: str) -> str | None:
    n = (name or "").strip().lower()
    if not n:
        return None
    aliases: dict[str, str] = {
        "chrome": "chrome.exe",
        "googlechrome": "chrome.exe",
        "edge": "msedge.exe",
        "microsoftedge": "msedge.exe",
        "notepad": "notepad.exe",
        "記事本": "notepad.exe",
    }
    return aliases.get(n, n)


def _windows_pathext_list() -> list[str]:
    pathext = os.environ.get("PATHEXT") or os.environ.get("Pathext") or ".EXE;.CMD;.BAT;.COM"
    out: list[str] = []
    for ext in pathext.split(";"):
        e = ext.strip()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        out.append(e.lower())
    return out or [".exe", ".cmd", ".bat", ".com"]


def _resolve_executable_from_path_env(cmd: str, path_env: str) -> str | None:
    """
    類似 OpenClaw：不呼叫 where.exe，改為掃 PATH/PATHEXT。
    - Windows：優先 .cmd，再 .exe，再其他
    """
    if not cmd:
        return None
    entries = [p for p in (path_env or "").split(";") if p]
    pathext = _windows_pathext_list()
    has_ext = os.path.splitext(cmd)[1] != ""
    candidates: list[str] = []
    for entry in entries:
        entry = entry.strip().strip('"')
        if not entry:
            continue
        if has_ext:
            p = os.path.join(entry, cmd)
            if os.path.isfile(p):
                return p
            continue
        for ext in pathext:
            p = os.path.join(entry, cmd + ext)
            if os.path.isfile(p):
                candidates.append(p)
    if not candidates:
        return None
    # prefer .cmd > .exe > first
    for prefer in (".cmd", ".exe"):
        for c in candidates:
            if c.lower().endswith(prefer):
                return c
    return candidates[0]


def _resolve_executable_from_app_paths(exe_name: str) -> str | None:
    """
    Windows Registry: HKLM/HKCU\\...\\App Paths\\<exe>
    這常用於 chrome.exe / msedge.exe 等。
    """
    try:
        import winreg  # type: ignore
    except Exception:
        return None

    subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{}".format(exe_name)
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, subkey) as k:
                val, _t = winreg.QueryValueEx(k, None)  # default value
                p = str(val).strip()
                if p and os.path.isfile(p):
                    return p
        except Exception:
            continue
    return None


def _common_install_paths(exe_name: str) -> list[str]:
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    # 常見安裝位置（不求完整，只求「大多數能用」）
    if exe_name.lower() == "chrome.exe":
        return [
            os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pfx86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local, r"Google\Chrome\Application\chrome.exe") if local else "",
        ]
    if exe_name.lower() in ("msedge.exe",):
        return [
            os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(pfx86, r"Microsoft\Edge\Application\msedge.exe"),
        ]
    return []


def _resolve_windows_command(cmd: str) -> str | None:
    """
    Windows：把裸命令解析成可啟動的路徑。
    順序：
    - 若已是路徑（含 \\ 或 /）：直接檢查存在
    - Registry App Paths
    - 常見安裝路徑（chrome/edge）
    - PATH + PATHEXT 掃描（OpenClaw 風格）
    """
    c = (cmd or "").strip().strip('"')
    if not c:
        return None
    if "\\" in c or "/" in c:
        return c if os.path.isfile(c) else None
    exe = c
    if os.path.splitext(exe)[1] == "":
        exe_name = exe + ".exe"
    else:
        exe_name = exe
    reg = _resolve_executable_from_app_paths(exe_name)
    if reg:
        return reg
    for p in _common_install_paths(exe_name):
        if p and os.path.isfile(p):
            return p
    env_path = os.environ.get("PATH") or os.environ.get("Path") or ""
    found = _resolve_executable_from_path_env(exe, env_path)
    if found:
        return found
    # 最後嘗試 exe_name（帶 .exe）再掃一次
    if exe_name != exe:
        found2 = _resolve_executable_from_path_env(exe_name, env_path)
        if found2:
            return found2
    return None


def _spawn_windows_shell_open(target: str) -> tuple[bool, str | None]:
    """
    交給 Windows Shell 解析（通用 fallback）：
    - 可能透過 App execution alias、Start Menu 捷徑、註冊表 App Paths 等成功啟動
    """
    t = (target or "").strip().strip('"')
    if not t:
        return False, "empty target"
    try:
        # cmd.exe 的 start 需要一個 title 參數（可為空字串）
        subprocess.Popen(["cmd", "/c", "start", "", t], shell=False)  # noqa: S603,S607
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _spawn_windows_command(resolved_path: str) -> tuple[bool, str | None]:
    """
    真的啟動程式。
    回傳 (ok, detail_error)。
    """
    try:
        low = resolved_path.lower()
        if low.endswith((".cmd", ".bat")):
            subprocess.Popen(["cmd", "/c", resolved_path], shell=False)  # noqa: S603,S607
        else:
            subprocess.Popen([resolved_path], shell=False)  # noqa: S603
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)

SKILLS: dict[str, SkillSpec] = _load_skill_specs_from_dirs()


def get_tool_catalog() -> list[dict[str, Any]]:
    """
    給 Planner / UI 的工具目錄。保持可序列化、可讀。
    """
    out: list[dict[str, Any]] = []
    for spec in SKILLS.values():
        out.append(
            {
                "name": spec.name,
                "aliases": list(spec.aliases),
                "description": spec.description,
                "risk_level": spec.risk_level,
                "requires_confirmation": spec.requires_confirmation,
                "args_schema": spec.args_schema,
            }
        )
    return out


def list_skill_names() -> list[str]:
    return sorted(SKILLS.keys())


def _resolve_skill_name(name: str) -> str | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    if key in SKILLS:
        return key
    for spec in SKILLS.values():
        if key in {a.lower() for a in (spec.aliases or [])}:
            return spec.name
    return None


def run_skill(name: str, args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    key = _resolve_skill_name(name)
    if key is None:
        shown = (name or "").strip() or "?"
        return SkillResult(ok=False, skill=shown, summary=f"未知技能：{name!r}", error="unknown_skill")
    spec = SKILLS[key]
    try:
        return spec.handler(args, ctx)
    except Exception as e:  # noqa: BLE001
        return SkillResult(
            ok=False,
            skill=spec.name,
            summary=f"技能執行失敗：{e}",
            error=str(e),
        )


# --- 使用者輸入中的 (skill:xxx ...) 語法 ---------------------------------

_SKILL_TOKEN_RE = re.compile(
    r"\(\s*skill\s*:\s*([a-zA-Z0-9_]+)\s+([^)]*)\)",
    re.IGNORECASE,
)

# 也支援「不加括號」的單行指令：skill:open_url https://...
# - 允許前面有空白
# - 只吃到該行結尾
_SKILL_BARE_LINE_RE = re.compile(
    r"^\s*skill\s*:\s*([a-zA-Z0-9_]+)\s+(.+?)\s*$",
    re.IGNORECASE,
)


def _parse_one_skill_call(name: str, rest: str) -> tuple[str, dict[str, Any]]:
    skill = (name or "").strip().lower()
    r = (rest or "").strip()
    args: dict[str, Any] = {}
    if not r:
        return skill, args

    # 允許把單一 token 當成 url / query / name（依 skill 不同而定）
    if " " not in r:
        if re.match(r"^https?://", r, re.I) or r.startswith("www."):
            args["url"] = r if r.startswith("http") else f"https://{r}"
            return skill, args
        if skill == "search_web":
            args["query"] = r
            return skill, args
        if skill == "open_app":
            args["name"] = r
            return skill, args
        if skill == "weather":
            args["location"] = r
            return skill, args
        if skill == "instant_answer":
            args["query"] = r
            return skill, args
        if skill == "fetch_url" and (re.match(r"^https?://", r, re.I) or r.startswith("www.")):
            args["url"] = r if r.startswith("http") else f"https://{r}"
            return skill, args

    # key=value 以空白分隔；未帶 key 的 token 視 skill 決定如何收集
    free_tokens: list[str] = []
    for part in r.split():
        if "=" in part:
            k, v = part.split("=", 1)
            args[k.strip().lower()] = v.strip()
        else:
            free_tokens.append(part)

    if free_tokens:
        if skill == "search_web":
            tail = " ".join(free_tokens)
            if "query" in args and str(args.get("query") or "").strip():
                args["query"] = f"{str(args['query']).strip()} {tail}".strip()
            else:
                args["query"] = tail
        elif skill == "open_app":
            args.setdefault("name", free_tokens[0])
        elif skill == "weather":
            args["location"] = " ".join(free_tokens)
        elif skill == "instant_answer":
            args["query"] = " ".join(free_tokens)
        elif skill == "fetch_url":
            for tok in free_tokens:
                if re.match(r"^https?://", tok, re.I):
                    args["url"] = tok
                    break
            else:
                args["url"] = free_tokens[-1]
        else:
            args.setdefault("url", free_tokens[-1])
    return skill, args


def parse_inline_skill_calls(text: str) -> list[tuple[str, dict[str, Any]]]:
    """
    解析 '(skill:open_url https://...)' 或 '(skill:open_url url=https://...)'
    也支援單行 'skill:open_url https://...'（不加括號）。
    回傳 (skill_name, args_dict) 列表，順序為出現順序。
    """
    out: list[tuple[str, dict[str, Any]]] = []
    src = text or ""
    for m in _SKILL_TOKEN_RE.finditer(src):
        out.append(_parse_one_skill_call(m.group(1), m.group(2) or ""))
    for line in src.splitlines():
        m = _SKILL_BARE_LINE_RE.match(line)
        if m:
            out.append(_parse_one_skill_call(m.group(1), m.group(2) or ""))
    return out


def strip_inline_skill_calls(text: str) -> str:
    src = text or ""
    src = _SKILL_TOKEN_RE.sub("", src)
    # 移除 bare skill 指令行
    kept: list[str] = []
    for line in src.splitlines():
        if _SKILL_BARE_LINE_RE.match(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()
