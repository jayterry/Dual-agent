"""本機 user profile 庫（DAI 建圖四欄＋Memory relations 參照）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from dual_agent.dai.fraud_dual.shared.constants import AGE_BANDS, CHANNELS, OCCUPATIONS

_DEFAULT_USER_ID = "desktop"

_PROFILE_FIELDS = ("age_band", "occupation", "primary_apps", "invest_exp")

# 中文關係稱謂 → 雙路封閉 relation_type
_RELATION_TO_CLOSED: dict[str, str] = {
    "兒子": "Family",
    "女兒": "Family",
    "媽媽": "Family",
    "父親": "Family",
    "爸爸": "Family",
    "母親": "Family",
    "老公": "Family",
    "老婆": "Family",
    "丈夫": "Family",
    "妻子": "Family",
    "哥哥": "Family",
    "弟弟": "Family",
    "姊姊": "Family",
    "姐姐": "Family",
    "妹妹": "Family",
    "家人": "Family",
    "朋友": "Friend",
    "好友": "Friend",
    "同事": "Colleague",
    "主管": "Colleague",
    "老闆": "Colleague",
    "專題組員": "Colleague",
    "組員": "Colleague",
}


def default_profile_db_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "user_profile.sqlite"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_profile_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS profile (
            user_id TEXT PRIMARY KEY,
            age_band TEXT,
            occupation TEXT,
            primary_apps TEXT,
            invest_exp TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS relations (
            user_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (user_id, relation, name)
        );
        """
    )
    conn.commit()


def _pick(raw: Any, allowed: tuple[str, ...], default: str | None = None) -> str | None:
    s = str(raw or "").strip()
    if s in allowed:
        return s
    return default


def _normalize_apps(raw: Any) -> list[str]:
    apps: list[str] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw.strip():
        items = [x.strip() for x in raw.replace("，", ",").split(",")]
    else:
        items = []
    for a in items:
        if str(a) in CHANNELS and str(a) not in apps:
            apps.append(str(a))
    return apps


def get_profile(user_id: str = _DEFAULT_USER_ID, *, db_path: Path | None = None) -> dict[str, Any]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT age_band, occupation, primary_apps, invest_exp FROM profile WHERE user_id=?",
            (user_id,),
        ).fetchone()
    if not row:
        return {
            "age_band": "25-39",
            "occupation": "other",
            "primary_apps": ["SMS"],
            "invest_exp": None,
        }
    apps = _normalize_apps(json.loads(row["primary_apps"] or "[]"))
    if not apps:
        apps = ["SMS"]
    return {
        "age_band": _pick(row["age_band"], AGE_BANDS, "25-39") or "25-39",
        "occupation": _pick(row["occupation"], OCCUPATIONS, "other") or "other",
        "primary_apps": apps,
        "invest_exp": (row["invest_exp"] or "").strip() or None,
    }


def upsert_fields(
    fields: dict[str, Any],
    *,
    user_id: str = _DEFAULT_USER_ID,
    db_path: Path | None = None,
) -> dict[str, Any]:
    cur = get_profile(user_id, db_path=db_path)
    if "age_band" in fields and fields["age_band"] not in (None, ""):
        cur["age_band"] = _pick(fields["age_band"], AGE_BANDS, cur["age_band"]) or cur["age_band"]
    if "occupation" in fields and fields["occupation"] not in (None, ""):
        cur["occupation"] = (
            _pick(fields["occupation"], OCCUPATIONS, cur["occupation"]) or cur["occupation"]
        )
    if "primary_apps" in fields and fields["primary_apps"] not in (None, ""):
        apps = _normalize_apps(fields["primary_apps"])
        if apps:
            cur["primary_apps"] = apps
    if "invest_exp" in fields:
        inv = fields["invest_exp"]
        cur["invest_exp"] = str(inv).strip() if inv not in (None, "") else None

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO profile (user_id, age_band, occupation, primary_apps, invest_exp, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                age_band=excluded.age_band,
                occupation=excluded.occupation,
                primary_apps=excluded.primary_apps,
                invest_exp=excluded.invest_exp,
                updated_at=datetime('now')
            """,
            (
                user_id,
                cur["age_band"],
                cur["occupation"],
                json.dumps(cur["primary_apps"], ensure_ascii=False),
                cur["invest_exp"],
            ),
        )
        conn.commit()
    return cur


def to_dai_persona(user_id: str = _DEFAULT_USER_ID, *, db_path: Path | None = None) -> dict[str, Any]:
    """僅四欄（不含 channel／relation_type；由系統推斷）。"""
    p = get_profile(user_id, db_path=db_path)
    out: dict[str, Any] = {
        "age_band": p["age_band"],
        "occupation": p["occupation"],
        "primary_apps": list(p["primary_apps"]),
    }
    if p.get("invest_exp"):
        out["invest_exp"] = p["invest_exp"]
    return out


def known_relations(
    user_id: str = _DEFAULT_USER_ID, *, db_path: Path | None = None
) -> dict[str, list[str]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT relation, name FROM relations WHERE user_id=? ORDER BY relation, name",
            (user_id,),
        ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        rel = str(r["relation"])
        name = str(r["name"])
        out.setdefault(rel, [])
        if name not in out[rel]:
            out[rel].append(name)
    return out


def upsert_relation(
    relation: str,
    name: str,
    *,
    mode: str = "set",
    user_id: str = _DEFAULT_USER_ID,
    db_path: Path | None = None,
) -> None:
    rel = str(relation or "").strip()
    val = str(name or "").strip()
    if not rel or not val:
        return
    with _connect(db_path) as conn:
        if mode == "set":
            conn.execute(
                "DELETE FROM relations WHERE user_id=? AND relation=?",
                (user_id, rel),
            )
        conn.execute(
            "INSERT OR IGNORE INTO relations (user_id, relation, name) VALUES (?, ?, ?)",
            (user_id, rel, val),
        )
        conn.commit()


def clear_relation(
    relation: str,
    *,
    user_id: str = _DEFAULT_USER_ID,
    db_path: Path | None = None,
) -> None:
    rel = str(relation or "").strip()
    if not rel:
        return
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM relations WHERE user_id=? AND relation=?",
            (user_id, rel),
        )
        conn.commit()


def sync_relations_from_user_facts(
    user_facts: dict[str, Any] | None,
    *,
    user_id: str = _DEFAULT_USER_ID,
    db_path: Path | None = None,
) -> None:
    """以 Memory user_facts.relations 整表覆寫 sqlite relations。"""
    relations = {}
    if isinstance(user_facts, dict):
        raw = user_facts.get("relations")
        if isinstance(raw, dict):
            relations = raw
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM relations WHERE user_id=?", (user_id,))
        for rel, names in relations.items():
            if not isinstance(names, list):
                continue
            for n in names:
                name = str(n or "").strip()
                if name:
                    conn.execute(
                        "INSERT OR IGNORE INTO relations (user_id, relation, name) VALUES (?, ?, ?)",
                        (user_id, str(rel), name),
                    )
        conn.commit()


def closed_relation_for_label(relation_label: str) -> str:
    lab = str(relation_label or "").strip()
    if lab in _RELATION_TO_CLOSED:
        return _RELATION_TO_CLOSED[lab]
    for k, v in _RELATION_TO_CLOSED.items():
        if k in lab:
            return v
    return "Unknown"


def match_known_name_in_text(
    text: str,
    *,
    user_id: str = _DEFAULT_USER_ID,
    db_path: Path | None = None,
    relations: dict[str, list[str]] | None = None,
) -> dict[str, Any] | None:
    """若正文出現已知人名，回傳命中之封閉 relation_type。"""
    t = text or ""
    rels = relations if relations is not None else known_relations(user_id, db_path=db_path)
    # 較長名字優先
    hits: list[tuple[int, str, str, str]] = []
    for rel, names in rels.items():
        for name in names:
            n = str(name).strip()
            if len(n) < 2:
                continue
            if n in t:
                hits.append((len(n), n, rel, closed_relation_for_label(rel)))
    if not hits:
        return None
    hits.sort(key=lambda x: -x[0])
    _len, name, rel, closed = hits[0]
    return {
        "relation_type": closed,
        "matched_name": name,
        "matched_relation_label": rel,
        "confidence": 0.92,
        "source": "known_relations",
        "note": f"name_hit:{name}->{rel}",
        "reason": f"內文出現已知聯絡人「{name}」（{rel}）",
    }


def resolve_profile_user_id(ctx: Any | None = None, *, fallback: str = _DEFAULT_USER_ID) -> str:
    """從 SkillContext.policy_state['profile_user_id'] 取本輪使用者 id。"""
    if ctx is None:
        return fallback
    ps = getattr(ctx, "policy_state", None)
    if not isinstance(ps, dict):
        return fallback
    uid = str(ps.get("profile_user_id") or "").strip()
    return uid or fallback


def load_persona_into_ctx(ctx: Any, *, user_id: str | None = None) -> dict[str, Any]:
    """寫入 policy_state['dai_persona'] 與 known_relations。"""
    uid = (user_id or "").strip() or resolve_profile_user_id(ctx)
    if uid:
        ctx.policy_state["profile_user_id"] = uid
    persona = to_dai_persona(uid)
    ctx.policy_state["dai_persona"] = dict(persona)
    kr = known_relations(uid)
    # 合併本 session 尚未同步完的 user_facts（同輪寫入後立刻可用）
    uf = ctx.policy_state.get("user_facts")
    if isinstance(uf, dict) and isinstance(uf.get("relations"), dict):
        for rel, names in uf["relations"].items():
            if not isinstance(names, list):
                continue
            bucket = kr.setdefault(str(rel), [])
            for n in names:
                name = str(n or "").strip()
                if name and name not in bucket:
                    bucket.append(name)
    ctx.policy_state["known_relations"] = kr
    return persona


def looks_like_money_not_name(value: str) -> bool:
    """金額／數字不當成人名。"""
    import re

    v = (value or "").strip()
    if not v:
        return True
    if re.search(r"\d", v) and re.search(r"萬|元|塊|千|億|圓|\$", v):
        return True
    if re.fullmatch(r"[\d,\.]+", v):
        return True
    if re.fullmatch(r"\d+[萬千億]?", v):
        return True
    return False
