from __future__ import annotations

import os
import subprocess
from typing import Any

from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "程式別名，例如 chrome/edge/notepad"},
        "path": {"type": "string", "description": "exe 完整路徑"},
    },
}


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
    for prefer in (".cmd", ".exe"):
        for c in candidates:
            if c.lower().endswith(prefer):
                return c
    return candidates[0]


def _resolve_executable_from_app_paths(exe_name: str) -> str | None:
    try:
        import winreg  # type: ignore
    except Exception:
        return None

    subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{}".format(exe_name)
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, subkey) as k:
                val, _t = winreg.QueryValueEx(k, None)
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
    c = (cmd or "").strip().strip('"')
    if not c:
        return None
    if "\\" in c or "/" in c:
        return c if os.path.isfile(c) else None
    exe = c
    exe_name = exe + ".exe" if os.path.splitext(exe)[1] == "" else exe
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
    if exe_name != exe:
        found2 = _resolve_executable_from_path_env(exe_name, env_path)
        if found2:
            return found2
    return None


def _spawn_windows_shell_open(target: str) -> tuple[bool, str | None]:
    t = (target or "").strip().strip('"')
    if not t:
        return False, "empty target"
    try:
        subprocess.Popen(["cmd", "/c", "start", "", t], shell=False)  # noqa: S603,S607
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _spawn_windows_command(resolved_path: str) -> tuple[bool, str | None]:
    try:
        low = resolved_path.lower()
        if low.endswith((".cmd", ".bat")):
            subprocess.Popen(["cmd", "/c", resolved_path], shell=False)  # noqa: S603,S607
        else:
            subprocess.Popen([resolved_path], shell=False)  # noqa: S603
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:  # noqa: ARG001
    path = (args.get("path") or "").strip()
    name = (args.get("name") or args.get("app") or "").strip()
    target = path or name
    if not target:
        return SkillResult(ok=False, skill="open_app", summary="缺少 name 或 path 參數", error="missing_target")

    try:
        if path:
            if not os.path.exists(path):
                return SkillResult(ok=False, skill="open_app", summary="找不到指定路徑", data={"path": path}, error="not_found")
            os.startfile(path)  # type: ignore[attr-defined]
            return SkillResult(ok=True, skill="open_app", summary=f"已嘗試開啟：{path}", data={"path": path})

        exe = _resolve_windows_app(name)
        if not exe:
            return SkillResult(ok=False, skill="open_app", summary="無法解析 app 名稱", data={"name": name}, error="invalid_name")
        resolved = _resolve_windows_command(exe)
        if resolved:
            ok, err = _spawn_windows_command(resolved)
            if ok:
                return SkillResult(ok=True, skill="open_app", summary=f"已嘗試開啟：{name}", data={"path": resolved})
            return SkillResult(
                ok=False,
                skill="open_app",
                summary=f"啟動失敗：{err}" if err else "啟動失敗",
                data={"name": name, "exe": exe, "resolved": resolved},
                error=err or "spawn_failed",
            )

        ok2, err2 = _spawn_windows_shell_open(exe)
        if ok2:
            return SkillResult(ok=True, skill="open_app", summary=f"已嘗試開啟：{name}", data={"target": exe, "via": "shell_start"})
        return SkillResult(
            ok=False,
            skill="open_app",
            summary="找不到程式（請改用 path=完整路徑，或確認已安裝）" if not err2 else f"找不到程式：{err2}",
            data={"name": name, "exe": exe},
            error=err2 or "not_found",
        )
    except FileNotFoundError:
        return SkillResult(
            ok=False,
            skill="open_app",
            summary="找不到程式（請改用 path=完整路徑，或確認已安裝/在 PATH）",
            data={"target": target},
            error="not_found",
        )
    except Exception as e:  # noqa: BLE001
        return SkillResult(ok=False, skill="open_app", summary=f"啟動失敗：{e}", data={"target": target}, error=str(e))

