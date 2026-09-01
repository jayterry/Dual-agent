"""DAI 雙路防詐適配：SMS／artifact → fraud_dual pipeline → 既有 report 契約。"""

from __future__ import annotations

import os
import re
import json
from typing import Any

from dual_agent.dai.fraud_dual.llm.ollama import OllamaConfig, OllamaError, chat_json
from dual_agent.dai.fraud_dual.pipeline import run_pipeline
from dual_agent.dai.fraud_dual.shared.constants import (
    AGE_BANDS,
    CHANNELS,
    OCCUPATIONS,
    RELATION_TYPES,
)
from dual_agent.dai.fraud_dual.shared.schemas import AnalyzeRequest, AnalyzeResponse, ResultA, ResultB
from dual_agent.dai.risk_analysis.review_display import (
    brief_safety_line,
    enrich_report_display_fields,
    verdict_display,
)
from dual_agent.dai.risk_analysis.verdict import recommended_cai_action, verdict_from_score
from dual_agent.dai.schemas import DAIRequest

_SCAM_REASON_ZH: dict[str, str] = {
    "Investment": "疑似投資誘導話術",
    "Loan": "疑似貸款詐騙話術",
    "Romance": "疑似情感／交友誘導",
    "Fake_CS": "疑似假冒客服",
    "OTP_Scam": "疑似索取驗證碼",
    "Job_Scam": "疑似求職詐騙",
    "Gov_Subsidy": "疑似假冒政府補助",
    "Impersonation_Authority": "疑似冒充機關或銀行",
    "Parcel": "疑似包裹／物流詐騙",
    "Account_Freeze": "疑似帳戶凍結恐嚇",
    "Unknown": "類型未明但內容具風險特徵",
}

_CHANNEL_FROM_SOURCE: dict[str, str] = {
    "sms": "SMS",
    "sms_share": "SMS",
    "desktop": "SMS",
    "email": "Email",
    "line": "LINE",
    "telegram": "Telegram",
    "facebook": "Facebook",
    "website": "Website",
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def score01_to_100(score: float) -> int:
    return int(round(_clamp01(score) * 100))


def _pick_closed(raw: Any, allowed: tuple[str, ...], default: str) -> str:
    s = str(raw or "").strip()
    if s in allowed:
        return s
    return default


def channel_from_source(source: str) -> str:
    key = (source or "").strip().lower()
    if key in _CHANNEL_FROM_SOURCE:
        return _CHANNEL_FROM_SOURCE[key]
    for k, v in _CHANNEL_FROM_SOURCE.items():
        if k in key:
            return v
    return "SMS"


def persona_from_request(req: DAIRequest, *, source: str = "") -> dict[str, Any]:
    """使用者側建圖欄位。relation_type／channel 預設佔位，由前置推斷覆寫。"""
    persona: dict[str, Any] = {}
    if getattr(req, "persona", None) and isinstance(req.persona, dict):
        persona.update(req.persona)
    ctx = dict(req.sender_tech_context or {})
    nested = ctx.get("persona") if isinstance(ctx.get("persona"), dict) else None
    if nested:
        for k, v in nested.items():
            persona.setdefault(k, v)
    else:
        for k in (
            "age_band",
            "occupation",
            "primary_apps",
            "invest_exp",
        ):
            if k in ctx and k not in persona:
                persona[k] = ctx[k]
    age = _pick_closed(persona.get("age_band"), AGE_BANDS, "25-39")
    occ = _pick_closed(persona.get("occupation"), OCCUPATIONS, "other")
    # sender／本則管道屬性：不以「個人設定」為準（允許測試／顯式 override）
    if _env_flag("DAI_DUAL_RELATION_OVERRIDE", False):
        rel = _pick_closed(persona.get("relation_type"), RELATION_TYPES, "Unknown")
    else:
        rel = "Unknown"
    src = source or req.source
    if _env_flag("DAI_DUAL_CHANNEL_OVERRIDE", False):
        ch = _pick_closed(persona.get("channel") or channel_from_source(src), CHANNELS, "SMS")
    else:
        ch = channel_from_source(src)
    apps_raw = persona.get("primary_apps")
    apps: list[str] = []
    if isinstance(apps_raw, list):
        for a in apps_raw:
            if str(a) in CHANNELS and str(a) not in apps:
                apps.append(str(a))
    elif isinstance(apps_raw, str) and apps_raw.strip():
        for a in apps_raw.split(","):
            a = a.strip()
            if a in CHANNELS and a not in apps:
                apps.append(a)
    if not apps:
        apps = [ch]
    invest = persona.get("invest_exp")
    invest_s = str(invest).strip() if invest not in (None, "") else None
    return {
        "age_band": age,
        "occupation": occ,
        "relation_type": rel,
        "channel": ch,
        "primary_apps": apps,
        "invest_exp": invest_s,
    }


_RELATION_HINTS: list[tuple[str, str]] = [
    (r"銀行|客服|官方|警方|165|戶政|健保|電信|中華電信|遠傳|台哥大|本部|法院|檢警", "Official"),
    (r"爸|媽|父親|母親|哥哥|弟弟|姊姊|姐姐|妹妹|家人|兒子|女兒|老婆|老公", "Family"),
    (r"同事|主管|老闆|課長|經理|公司", "Colleague"),
    (r"朋友|好友|學長|學弟|學姊|學妹", "Friend"),
]

_CHANNEL_HINTS: list[tuple[str, str]] = [
    (r"line\.me|lin\.ee|加入.?line|line\s*官方|＠line|@line|line\s*id", "LINE"),
    (r"t\.me/|telegram|电报|電報", "Telegram"),
    (r"facebook\.com|fb\.com|臉書|粉丝专页|粉絲專頁", "Facebook"),
    (r"mailto:|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "Email"),
    (r"https?://|www\.", "Website"),
    (r"簡訊|短信|sms\b|門號簡訊", "SMS"),
]


def relation_from_heuristics(text: str) -> tuple[str, float, str]:
    """輕量關鍵詞推斷；回傳 (relation, confidence, note)。"""
    t = text or ""
    for pat, rel in _RELATION_HINTS:
        if re.search(pat, t, re.I):
            return rel, 0.72, f"heuristic:{pat}"
    return "Unknown", 0.35, "heuristic:no_match"


def channel_from_heuristics(text: str, *, source_fallback: str = "SMS") -> tuple[str, float, str]:
    """從本文推斷本則發送管道；無命中則回 source_fallback（低信心）。"""
    t = text or ""
    for pat, ch in _CHANNEL_HINTS:
        if re.search(pat, t, re.I):
            # Email 僅靠 @ 較寬，略降信心；明確平台連結較高
            conf = 0.68 if ch == "Email" else 0.78
            if ch == "Website" and re.search(r"line\.me|t\.me/|facebook\.com", t, re.I):
                continue
            return ch, conf, f"heuristic:{pat}"
    fb = _pick_closed(source_fallback, CHANNELS, "SMS")
    return fb, 0.45, f"source_fallback:{fb}"


_RELATION_SYSTEM = """你是反詐騙系統的來訊關係推斷器。
任務：依訊息本文、管道、使用者已知聯絡人，判斷發送者與收件者的關係，只輸出 JSON。
硬性規則：
1. 只輸出 JSON，不要 Markdown。
2. 欄位：relation_type（字串）、confidence（0~1）、reason（繁中短句）。
3. relation_type 只能是：Family, Friend, Colleague, Official, Unknown
4. 自稱銀行／機關／客服／物流官方 → Official
5. 若 known_relations 中的人名出現在訊息內，優先採用對應家人／朋友／同事映射
6. 無清楚身分線索 → Unknown（勿猜熟人）
7. 不可讀取或捏造威脅分數。"""


_CHANNEL_SYSTEM = """你是反詐騙系統的「本則訊息發送管道」推斷器。
任務：判斷這則可疑訊息是透過哪個 App／管道送來的，只輸出 JSON。
注意：這不是使用者「常用 App」，而是「這則訊息本身」的發送管道；primary_apps 僅作 prior 參考。
硬性規則：
1. 只輸出 JSON，不要 Markdown。
2. 欄位：channel（字串）、confidence（0~1）、reason（繁中短句）。
3. channel 只能是：LINE, Telegram, SMS, Email, Facebook, Website
4. 有 line.me／加入 LINE → LINE；t.me → Telegram；郵件格式 → Email；一般網址且無特定 App → Website
5. 典型銀行／OTP 簡訊且無其他 App 線索 → SMS
6. 線索不足時採 hint_channel；可參考 primary_apps，並降低 confidence
7. 不可讀取或捏造威脅分數。"""


def infer_sender_relation(
    text: str,
    *,
    channel: str,
    model: str,
    base_url: str,
    temperature: float = 0.0,
    known_relations: dict[str, list[str]] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Path A／B 共用之前置推斷 sender relation。
    優先：已知人名命中 → 啟發式 → LLM（可帶 profile／relations 參照）。
    """
    from dual_agent.cai.profile_store import match_known_name_in_text

    hit = match_known_name_in_text(text, relations=known_relations)
    if hit and hit.get("relation_type") and hit["relation_type"] != "Unknown":
        return hit

    heur_rel, heur_conf, heur_note = relation_from_heuristics(text)
    out: dict[str, Any] = {
        "relation_type": heur_rel,
        "confidence": heur_conf,
        "source": "heuristic",
        "note": heur_note,
        "reason": "",
    }
    # 高信心啟發式可直接用（Official／家人等）
    if heur_rel != "Unknown" and heur_conf >= 0.7:
        return out

    if not _env_flag("DAI_DUAL_INFER_RELATION", True):
        return out

    import json

    try:
        cfg = OllamaConfig(
            host=base_url.rstrip("/"),
            model=model,
            temperature=max(0.0, float(temperature or 0.0)),
            timeout_s=float(os.environ.get("RELATION_INFER_TIMEOUT", "45")),
        )
        user = json.dumps(
            {
                "message_text": (text or "")[:1200],
                "channel": channel,
                "user_profile": {
                    "age_band": (profile or {}).get("age_band"),
                    "occupation": (profile or {}).get("occupation"),
                    "primary_apps": (profile or {}).get("primary_apps"),
                },
                "known_relations": known_relations or {},
                "allowed_relation_types": list(RELATION_TYPES),
                "output_schema_example": {
                    "relation_type": "Unknown",
                    "confidence": 0.5,
                    "reason": "一句理由",
                },
            },
            ensure_ascii=False,
        )
        raw = chat_json(system=_RELATION_SYSTEM, user=user, config=cfg)
        data = json.loads(raw)
        rel = _pick_closed(data.get("relation_type"), RELATION_TYPES, "Unknown")
        conf = float(data.get("confidence") if data.get("confidence") is not None else 0.5)
        conf = max(0.0, min(1.0, conf))
        reason = str(data.get("reason") or "").strip()[:160]
        # LLM 低信心時保留啟發式結果（若啟發式也是 Unknown 則採用 LLM）
        if rel == "Unknown" and heur_rel != "Unknown":
            out["note"] = f"{heur_note};llm_unknown"
            return out
        return {
            "relation_type": rel,
            "confidence": conf,
            "source": "llm",
            "note": "ok",
            "reason": reason,
        }
    except (OllamaError, json.JSONDecodeError, TypeError, ValueError, Exception) as e:  # noqa: BLE001
        out["note"] = f"llm_failed:{e}"
        return out


def infer_message_channel(
    text: str,
    *,
    source: str,
    model: str,
    base_url: str,
    temperature: float = 0.0,
    primary_apps: list[str] | None = None,
) -> dict[str, Any]:
    """
    Path A／B 共用之前置推斷本則發送管道（channel）。
    失敗或關閉 LLM 時：啟發式 → source 對應；可參照 primary_apps prior。
    """
    fallback = channel_from_source(source)
    apps = [a for a in (primary_apps or []) if a in CHANNELS]
    # 常用 App 單一明確時略提高 source 不足時的 prior
    if len(apps) == 1 and fallback == "SMS" and apps[0] != "SMS":
        # 正文無線索時仍以 source 為準；僅當啟發式低信心才考慮常用 App
        pass

    heur_ch, heur_conf, heur_note = channel_from_heuristics(text, source_fallback=fallback)
    out: dict[str, Any] = {
        "channel": heur_ch,
        "confidence": heur_conf,
        "source": "heuristic" if heur_conf >= 0.6 else "source_fallback",
        "note": heur_note,
        "reason": "",
    }
    if heur_conf >= 0.75:
        out["source"] = "heuristic"
        return out

    if not _env_flag("DAI_DUAL_INFER_CHANNEL", True):
        if heur_conf < 0.6 and len(apps) == 1:
            return {
                "channel": apps[0],
                "confidence": 0.55,
                "source": "primary_apps_prior",
                "note": f"primary_apps:{apps[0]}",
                "reason": "依使用者常用 App 作為低信心 prior",
            }
        return out

    import json

    try:
        cfg = OllamaConfig(
            host=base_url.rstrip("/"),
            model=model,
            temperature=max(0.0, float(temperature or 0.0)),
            timeout_s=float(os.environ.get("CHANNEL_INFER_TIMEOUT", "45")),
        )
        user = json.dumps(
            {
                "message_text": (text or "")[:1200],
                "hint_channel": fallback,
                "source_tag": source,
                "primary_apps": apps,
                "allowed_channels": list(CHANNELS),
                "output_schema_example": {
                    "channel": "SMS",
                    "confidence": 0.5,
                    "reason": "一句理由",
                },
            },
            ensure_ascii=False,
        )
        raw = chat_json(system=_CHANNEL_SYSTEM, user=user, config=cfg)
        data = json.loads(raw)
        ch = _pick_closed(data.get("channel"), CHANNELS, fallback)
        conf = float(data.get("confidence") if data.get("confidence") is not None else 0.5)
        conf = max(0.0, min(1.0, conf))
        reason = str(data.get("reason") or "").strip()[:160]
        # LLM 低信心時保留較強啟發式
        if conf < 0.45 and heur_conf >= 0.65:
            out["note"] = f"{heur_note};llm_low_conf"
            return out
        return {
            "channel": ch,
            "confidence": conf,
            "source": "llm",
            "note": "ok",
            "reason": reason,
        }
    except (OllamaError, json.JSONDecodeError, TypeError, ValueError, Exception) as e:  # noqa: BLE001
        out["note"] = f"llm_failed:{e}"
        return out


def explain_low_context(
    result_a: ResultA,
    *,
    channel: str = "",
    relation: str = "",
    primary_apps: list[str] | None = None,
) -> str | None:
    """當 Context 明顯低於 Threat 時，給出可稽核說明（禁止「沒提供背景」這種臆測）。"""
    if result_a.threat_score < 0.55 or result_a.context_score >= 0.4:
        return None
    apps = [str(a) for a in (primary_apps or [])]
    ch = str(channel or "").strip()
    rel = str(relation or "").strip() or "Unknown"
    familiar = bool(ch and ch in apps)
    bits: list[str] = []
    if familiar:
        bits.append(f"管道「{ch}」在常用清單內（熟悉管道，不加「非常用管道」分）")
    elif ch:
        bits.append(f"管道「{ch}」雖未必熟悉，但其他情境加成也未觸發")
    if rel == "Unknown":
        bits.append("關係為 Unknown，但誘導／其他加權仍偏低")
    else:
        bits.append(f"關係推斷為「{rel}」（非陌生 Unknown，陌生寄件人加權未觸發）")
    if rel == "Official" and str(result_a.scam_type) != "Fake_CS":
        bits.append("未命中「自稱官方＋假客服」組合，故無該項高情境加成")
    if not bits:
        bits.append("未命中非常用管道／陌生高誘因／高齡脆弱等情境規則")
    return (
        "情境分偏低≠安全：情境分只衡量「對此人／此管道／此人設是否特別危險」。"
        + "；".join(bits)
        + "。話術風險已由威脅分反映。"
    )


def path_a_reasons(
    result_a: ResultA,
    *,
    text: str = "",
    channel: str = "",
    relation: str = "",
    primary_apps: list[str] | None = None,
) -> list[str]:
    out: list[str] = []
    scam = str(result_a.scam_type)
    out.append(_SCAM_REASON_ZH.get(scam, f"詐騙類型：{scam}"))
    if result_a.threat_score >= 0.55:
        out.append(f"Threat 評分偏高（{score01_to_100(result_a.threat_score)}/100）")
    if result_a.context_score >= 0.55:
        out.append(f"Context 情境風險偏高（{score01_to_100(result_a.context_score)}/100）")
    note = explain_low_context(
        result_a,
        channel=channel,
        relation=relation,
        primary_apps=primary_apps,
    )
    if note:
        out.append(note)
    if result_a.threat_missing:
        out.append("Threat 模型標記為缺值／不確定")
    t = (text or "").lower()
    if re.search(r"驗證碼|otp|一次性密碼", t, re.I):
        out.append("文字含驗證碼／OTP 索取特徵")
    if re.search(r"密碼|帳密", t):
        out.append("文字含密碼／帳密索取特徵")
    if re.search(r"https?://|www\.", t):
        out.append("文字含連結")
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq[:6]


def path_a_warnings(result_a: ResultA) -> list[str]:
    warnings: list[str] = []
    gate = max(result_a.threat_score, result_a.context_score)
    if gate >= 0.85:
        warnings.append("高風險：建議阻擋，勿點連結／勿提供驗證碼或匯款")
    elif gate >= 0.55:
        warnings.append("中高風險：請提高警覺，向官方管道查證後再回應")
    else:
        warnings.append("分數偏低仍請留意來路")
    if result_a.threat_score >= 0.7 and result_a.context_score < 0.4:
        warnings.append(
            "威脅高、情境低：內容話術危險，但「對你這組人設／管道」的情境加成不高"
            "（常見於熟悉管道＋非陌生關係）。仍應依威脅分提高警覺，勿依指示操作"
        )
    if result_a.context_score >= 0.7 and result_a.threat_score < 0.4:
        warnings.append("對此對象情境風險偏高——即使話術表面溫和也請查證")
    return warnings[:5]


def path_b_reasons(result_b: ResultB) -> list[str]:
    out: list[str] = []
    expl = str(result_b.explanation or "").strip()
    if expl:
        out.append(expl[:160])
    scam = str(result_b.llm_scam_type)
    out.append(_SCAM_REASON_ZH.get(scam, f"LLM 類型：{scam}"))
    if result_b.llm_threat >= 0.55:
        out.append(f"LLM Threat {score01_to_100(result_b.llm_threat)}/100")
    if result_b.llm_context >= 0.55:
        out.append(f"LLM Context {score01_to_100(result_b.llm_context)}/100")
    if not result_b.llm_channel_familiar:
        out.append("當前管道不在常用 App 清單")
    seen: set[str] = set()
    uniq: list[str] = []
    for r in out:
        if r and r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq[:6]


def path_b_warnings(result_b: ResultB) -> list[str]:
    gate = max(result_b.llm_threat, result_b.llm_context)
    if gate >= 0.85:
        return ["Path B 判定高風險：建議阻擋"]
    if gate >= 0.55:
        return ["Path B 判定中高風險：請查證來源"]
    return ["Path B 分數偏低，仍請留意"]


def format_dual_display(
    *,
    path_a: dict[str, Any],
    path_b: dict[str, Any] | None,
    gate_score: int,
    verdict: str,
    narrator: str | None,
    suggestions: list[str],
) -> str:
    lines = [
        f"門檻分數（CAI）：{gate_score}/100　判定：{verdict_display(verdict)}",
        "",
        "—— Path A（ML Threat + Context）——",
        f"Threat：{path_a.get('threat_score_100', 0)}/100",
        f"Context：{path_a.get('context_score_100', 0)}/100",
        f"類型：{path_a.get('scam_type', 'Unknown')}",
        "原因：",
    ]
    for r in path_a.get("reasons") or []:
        lines.append(f"• {r}")
    lines.append("警示：")
    for w in path_a.get("warnings") or []:
        lines.append(f"• {w}")

    lines.append("")
    lines.append("—— Path B（純 LLM）——")
    if not path_b or path_b.get("skipped"):
        note = (path_b or {}).get("note") or "略過或失敗"
        lines.append(f"（{note}）")
    else:
        lines.append(f"Threat：{path_b.get('threat_score_100', 0)}/100")
        lines.append(f"Context：{path_b.get('context_score_100', 0)}/100")
        lines.append(f"類型：{path_b.get('scam_type', 'Unknown')}")
        lines.append("原因：")
        for r in path_b.get("reasons") or []:
            lines.append(f"• {r}")
        lines.append("警示：")
        for w in path_b.get("warnings") or []:
            lines.append(f"• {w}")

    if narrator:
        lines.append("")
        lines.append("—— LLM 分析報告 ——")
        lines.append(narrator.strip()[:900])

    if suggestions:
        lines.append("")
        lines.append("建議：")
        for s in suggestions:
            lines.append(f"• {s}")
    return "\n".join(lines).strip()


_NARRATOR_SYSTEM = """你是反詐騙助手的解說員（Narrator）。
任務：用繁體中文、簡潔清楚，向「這位使用者」解釋分數；解釋情境分時必須個人化。

分數定義（必須遵守）：
- 威脅分：訊息內容像不像詐騙話術。
- 情境分：在「此人設／推斷關係／管道熟悉度」下是否特別危險。低分＝對此人的情境加權未觸發，不是缺資料、不是安全。
- 閘道分：max(威脅, 情境)。

個人化硬規則（違規即失敗）：
1. 解釋情境分時，必須明確點名至少 3 項實際提供的個人化欄位，並寫出其值，例如：
   「你的年齡帶是 25-39」「職業設定為 office（上班族）」「常用管道含 SMS」「投資經驗：無／有填寫內容」「本則關係推斷為 Official」。
2. 必須說明這些欄位如何影響情境分（觸發或未觸發哪類加權），不可只講空泛的「依個人情況」。
3. 不得捏造未提供的欄位；若 invest_exp 為空，要說「未填投資經驗」或「投資經驗未設定」。
4. 禁止：「沒提供背景所以情境 0」「資料不足所以 0」「情境 0＝沒風險」。

輸出結構（勿用 # 標題）：
1) 分數怎麼來：分開講威脅／情境；情境段必須含個人化點名。
2) 判斷依據：引用 reasons／warnings 與推斷關係／管道。
3) 你可以怎麼做：一句務實建議。

只輸出說明文字，不要 JSON。"""


_OCC_ZH = {
    "student": "學生",
    "office": "上班族",
    "freelance": "自由業",
    "retired": "退休",
    "other": "其他",
}


def build_persona_cite_lines(persona: dict[str, Any] | None) -> list[str]:
    """給 Narrator 的強制可引用句子（含欄位值）。"""
    p = persona or {}
    age = str(p.get("age_band") or "").strip() or "（未設定，預設 25-39）"
    occ = str(p.get("occupation") or "").strip() or "other"
    occ_zh = _OCC_ZH.get(occ, occ)
    apps = p.get("primary_apps") or []
    if isinstance(apps, str):
        apps_list = [x.strip() for x in apps.replace("，", ",").split(",") if x.strip()]
    else:
        apps_list = [str(a).strip() for a in apps if str(a).strip()]
    apps_txt = "、".join(apps_list) if apps_list else "（未設定，預設 SMS）"
    inv = p.get("invest_exp")
    if inv in (None, ""):
        inv_txt = "未填"
    else:
        inv_txt = str(inv).strip()
    ch = str(p.get("channel") or "").strip() or "SMS"
    rel = str(p.get("relation_type") or "").strip() or "Unknown"
    familiar = bool(ch and ch in apps_list)
    lines = [
        f"年齡帶：{age}",
        f"職業：{occ}（{occ_zh}）",
        f"常用管道：{apps_txt}",
        f"投資經驗：{inv_txt}",
        f"本則推斷管道：{ch}（{'在常用清單＝熟悉管道' if familiar else '不在常用清單＝可能加陌生管道情境分'}）",
        f"本則推斷關係：{rel}",
    ]
    # 可解釋的情境加權提示（規則語意，供 LLM 引用，非重算）
    hints: list[str] = []
    if familiar:
        hints.append("熟悉管道 → 不加「非常用管道」情境分")
    else:
        hints.append("非常用管道 → 通常會提高情境分")
    if rel == "Unknown":
        hints.append("陌生關係 → 通常會提高情境分")
    else:
        hints.append(f"關係為 {rel}（非 Unknown）→ 不加「陌生寄件人」情境分")
    if rel == "Official":
        hints.append("Official 只有在同時判成 Fake_CS 時才有「偽官方」高情境加成")
    if age == "60+":
        hints.append("高齡 60+ → 對高風險類型／payload 較易加情境分")
    if occ == "retired":
        hints.append("退休身分撞上投資誘導時較易加情境分")
    if occ == "student":
        hints.append("學生身分撞上貸款／打工類時較易加情境分")
    if inv_txt in {"未填", "無", "沒有", "none", "no", "0"}:
        hints.append("投資經驗未填或無經驗時，投資誘導可能略增情境分（若規則／模型有觸發）")
    lines.append("情境加權提示：" + "；".join(hints))
    return lines


def _normalize_narrator_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    # 若模型仍回 JSON，取出說明欄位
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                for key in ("report", "explanation", "analysis", "summary", "text", "narrator"):
                    val = obj.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                # 拼接常見段落欄位
                parts = [
                    str(obj[k]).strip()
                    for k in ("分數怎麼來", "判斷依據", "你可以怎麼做", "score", "basis", "advice")
                    if isinstance(obj.get(k), str) and str(obj.get(k)).strip()
                ]
                if parts:
                    return "\n".join(parts)
        except json.JSONDecodeError:
            pass
    return text


def run_narrator(
    result_a: ResultA,
    *,
    graph_summary: dict[str, Any],
    model: str,
    base_url: str,
    temperature: float = 0.1,
    reasons: list[str] | None = None,
    warnings: list[str] | None = None,
    gate_score: int | None = None,
    path_b_summary: dict[str, Any] | None = None,
    persona: dict[str, Any] | None = None,
) -> str:
    from dual_agent.dai.fraud_dual.llm.ollama import chat_text

    threat100 = score01_to_100(result_a.threat_score)
    context100 = score01_to_100(result_a.context_score)
    gate = int(gate_score) if gate_score is not None else max(threat100, context100)
    persona_lines = build_persona_cite_lines({**(persona or {}), **(graph_summary or {})})
    payload = {
        "score_definitions": {
            "threat": "訊息內容像不像詐騙話術",
            "context": "對此使用者／管道／關係的情境加權；低分＝加權未觸發，不是缺資料、不是安全",
            "gate": "max(threat, context)",
        },
        "must_cite_these_user_facts": persona_lines,
        "threat_score_100": threat100,
        "context_score_100": context100,
        "gate_score_100": gate,
        "gate_rule": "max(threat, context)",
        "scam_type": result_a.scam_type,
        "intent_confidence": result_a.intent_confidence,
        "reasons": list(reasons or [])[:8],
        "warnings": list(warnings or [])[:5],
        "path_b_reference": path_b_summary,
    }
    user = (
        "請依下列資料撰寫個人化分析報告。"
        "解釋情境分時，必須逐一引用 must_cite_these_user_facts 中至少 3 項（含數值／選項原文），"
        "並說明它們如何讓情境分偏高或偏低。禁止說缺背景。勿重算分數：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    cfg = OllamaConfig(
        host=base_url.rstrip("/"),
        model=model,
        temperature=temperature,
        timeout_s=float(os.environ.get("NARRATOR_TIMEOUT", "90")),
    )
    raw = chat_text(system=_NARRATOR_SYSTEM, user=user, config=cfg)
    text = _normalize_narrator_text(raw)[:900]
    # 若模型仍未點名關鍵欄位，附加可稽核個人化摘要（保證使用者看得到）
    keys = ("年齡帶", "職業", "常用管道", "投資經驗", "推斷關係", "推斷管道")
    cited = sum(1 for k in keys if k in text)
    if cited < 2 and persona_lines:
        footer = "【本輪個人化參照】" + "；".join(persona_lines[:6])
        text = (text + "\n\n" + footer).strip()[:900]
    return text


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def build_analyze_request(
    req: DAIRequest,
    *,
    source: str = "",
    include_path_b: bool | None = None,
    include_narrator: bool | None = None,
    persona: dict[str, Any] | None = None,
) -> AnalyzeRequest:
    text = (req.artifact or req.user_text or "").strip()
    if not text:
        raise ValueError("empty artifact/user_text")
    p = dict(persona) if persona is not None else persona_from_request(req, source=source)
    return AnalyzeRequest(
        text=text,
        age_band=p["age_band"],  # type: ignore[arg-type]
        occupation=p["occupation"],  # type: ignore[arg-type]
        relation_type=p["relation_type"],  # type: ignore[arg-type]
        channel=p["channel"],  # type: ignore[arg-type]
        primary_apps=p["primary_apps"],  # type: ignore[arg-type]
        invest_exp=p["invest_exp"],
        include_path_b=_env_flag("DAI_DUAL_PATH_B", True) if include_path_b is None else include_path_b,
        include_narrator=_env_flag("DAI_DUAL_NARRATOR", True)
        if include_narrator is None
        else include_narrator,
    )


def analyze_response_to_report(
    resp: AnalyzeResponse,
    *,
    text: str,
    source: str,
    persona: dict[str, Any],
    model: str,
    base_url: str,
    path_b_note: str = "",
) -> dict[str, Any]:
    if resp.result_a is None:
        raise RuntimeError(f"Path A missing: {resp.detail}")

    ra = resp.result_a
    threat100 = score01_to_100(ra.threat_score)
    context100 = score01_to_100(ra.context_score)
    gate = max(threat100, context100)
    verdict = verdict_from_score(gate)
    action = recommended_cai_action(verdict, gate, r_rules=0)

    path_a_block = {
        "threat_score": ra.threat_score,
        "context_score": ra.context_score,
        "threat_score_100": threat100,
        "context_score_100": context100,
        "scam_type": ra.scam_type,
        "intent_confidence": ra.intent_confidence,
        "threat_missing": ra.threat_missing,
        "reasons": path_a_reasons(
            ra,
            text=text,
            channel=str(persona.get("channel") or ""),
            relation=str(persona.get("relation_type") or ""),
            primary_apps=list(persona.get("primary_apps") or []),
        ),
        "warnings": path_a_warnings(ra),
    }

    path_b_block: dict[str, Any] | None
    if resp.result_b is None:
        path_b_block = {
            "skipped": True,
            "note": path_b_note or (resp.detail or "Path B skipped"),
        }
    else:
        rb = resp.result_b
        path_b_block = {
            "skipped": False,
            "threat_score": rb.llm_threat,
            "context_score": rb.llm_context,
            "threat_score_100": score01_to_100(rb.llm_threat),
            "context_score_100": score01_to_100(rb.llm_context),
            "scam_type": rb.llm_scam_type,
            "llm_channel_familiar": rb.llm_channel_familiar,
            "explanation": rb.explanation,
            "reasons": path_b_reasons(rb),
            "warnings": path_b_warnings(rb),
        }

    narrator_text = resp.narrator_text
    narrator_note = ""
    # Narrator 由外層注入（此函式可直接用 resp.narrator_text）

    suggestions = list(path_a_block["warnings"][:2])
    if path_b_block and not path_b_block.get("skipped"):
        for w in path_b_block.get("warnings") or []:
            if w not in suggestions:
                suggestions.append(w)
    suggestions = suggestions[:5]

    display = format_dual_display(
        path_a=path_a_block,
        path_b=path_b_block,
        gate_score=gate,
        verdict=verdict,
        narrator=narrator_text,
        suggestions=suggestions,
    )

    labels = [str(ra.scam_type)]
    if path_b_block and not path_b_block.get("skipped") and path_b_block.get("scam_type"):
        labels.append(f"llm:{path_b_block['scam_type']}")

    report: dict[str, Any] = {
        "engine": "fraud_dual",
        "risk_score": gate,
        "risk_score_total": gate,
        "risk_score_total_user_fused": gate,
        "verdict": verdict,
        "gate_tier": verdict if verdict in ("allow", "warn", "block") else "quarantine",
        "recommended_cai_action": action,
        "dominant_source": "path_a_max_threat_context",
        "labels": labels,
        "component_scores": {
            "threat_score_100": threat100,
            "context_score_100": context100,
            "gate_score": gate,
            "path_b_threat_100": int(path_b_block.get("threat_score_100") or 0)
            if path_b_block
            else 0,
            "path_b_context_100": int(path_b_block.get("context_score_100") or 0)
            if path_b_block
            else 0,
        },
        "path_a": path_a_block,
        "path_b": path_b_block,
        "narrator_text": narrator_text,
        "narrator_note": narrator_note,
        "persona": persona,
        "relation_inferred": persona.get("relation_inferred"),
        "channel_inferred": persona.get("channel_inferred"),
        "dual_status": resp.status,
        "dual_detail": resp.detail,
        "dual_phase": resp.phase,
        "evidence": [
            {
                "type": "fraud_dual_path_a",
                "threat_score": ra.threat_score,
                "context_score": ra.context_score,
                "scam_type": ra.scam_type,
            }
        ],
        "reason_highlights": list(path_a_block["reasons"]),
        "user_reason_highlights": list(path_a_block["reasons"]),
        "user_suggestions": suggestions,
        "display_text": display,
        "safety_summary": brief_safety_line(gate, verdict)
        if not narrator_text
        else str(narrator_text)[:400],
        "archive_note": f"fraud_dual gate={gate} verdict={verdict} status={resp.status}",
        "track_a": {"matched_rules": [], "engine": "fraud_dual"},
        "analysis_payload": {"text": text[:500], "source": source},
        "model": model,
        "base_url": base_url,
    }
    enrich_report_display_fields(report, text=text, source=source)
    # enrich 會覆寫 display／reasons；雙路版再寫回
    report["user_reason_highlights"] = list(path_a_block["reasons"])
    report["user_suggestions"] = suggestions
    report["display_text"] = display
    if narrator_text:
        report["safety_summary"] = str(narrator_text)[:400]
    return report


def run_dual_path_analysis(
    req: DAIRequest,
    *,
    model: str,
    base_url: str,
    temperature: float = 0.0,
    source: str = "desktop",
    include_path_b: bool | None = None,
    include_narrator: bool | None = None,
    pipeline_ctx: Any | None = None,
) -> dict[str, Any]:
    """執行雙路分析並回傳 DAI report dict。"""
    from dual_agent.cai.pipeline_progress import advance_dual_phase

    persona = persona_from_request(req, source=source)
    text = (req.artifact or req.user_text or "").strip()

    known = None
    ctx_tech = dict(req.sender_tech_context or {})
    if isinstance(ctx_tech.get("known_relations"), dict):
        known = ctx_tech.get("known_relations")
    elif isinstance(persona.get("known_relations"), dict):
        known = persona.get("known_relations")

    # 前置：先推斷本則發送管道，再推斷來訊關係（Path A／B 共用）
    advance_dual_phase(pipeline_ctx, "infer", model=model)
    ch_meta = infer_message_channel(
        text,
        source=source or req.source or "desktop",
        model=model,
        base_url=base_url,
        temperature=temperature,
        primary_apps=list(persona.get("primary_apps") or []),
    )
    persona["channel"] = ch_meta["channel"]
    persona["channel_inferred"] = ch_meta

    rel_meta = infer_sender_relation(
        text,
        channel=str(persona.get("channel") or "SMS"),
        model=model,
        base_url=base_url,
        temperature=temperature,
        known_relations=known if isinstance(known, dict) else None,
        profile=persona,
    )
    persona["relation_type"] = rel_meta["relation_type"]
    persona["relation_inferred"] = rel_meta

    analyze_req = build_analyze_request(
        req,
        source=source,
        include_path_b=include_path_b,
        include_narrator=include_narrator,
        persona=persona,
    )

    # Path A（＋可選 Path B）使用與 DAI 相同的 Ollama
    advance_dual_phase(pipeline_ctx, "path_a", model=model)
    prev_host = os.environ.get("OLLAMA_HOST")
    prev_model = os.environ.get("OLLAMA_MODEL")
    os.environ["OLLAMA_HOST"] = base_url.rstrip("/")
    os.environ["OLLAMA_MODEL"] = model
    path_b_note = ""
    try:
        if analyze_req.include_path_b:
            advance_dual_phase(pipeline_ctx, "path_b", model=model)
        resp = run_pipeline(analyze_req)
        path_b_note = ""
        if analyze_req.include_path_b and resp.result_b is None:
            # 從 detail 抽 Path B 失敗原因
            detail = str(resp.detail or "")
            if "Path B" in detail:
                path_b_note = detail
            else:
                path_b_note = "Path B skipped or failed"
    finally:
        if prev_host is None:
            os.environ.pop("OLLAMA_HOST", None)
        else:
            os.environ["OLLAMA_HOST"] = prev_host
        if prev_model is None:
            os.environ.pop("OLLAMA_MODEL", None)
        else:
            os.environ["OLLAMA_MODEL"] = prev_model

    narrator_text: str | None = None
    narrator_note = ""
    if analyze_req.include_narrator and resp.result_a is not None:
        advance_dual_phase(pipeline_ctx, "narrator", model=model)
        try:
            ra = resp.result_a
            threat100 = score01_to_100(ra.threat_score)
            context100 = score01_to_100(ra.context_score)
            gate = max(threat100, context100)
            reasons = path_a_reasons(
                ra,
                text=text,
                channel=str(persona.get("channel") or ""),
                relation=str(persona.get("relation_type") or ""),
                primary_apps=list(persona.get("primary_apps") or []),
            )
            warnings = path_a_warnings(ra)
            ch_inf = persona.get("channel_inferred") if isinstance(persona.get("channel_inferred"), dict) else {}
            rel_inf = (
                persona.get("relation_inferred") if isinstance(persona.get("relation_inferred"), dict) else {}
            )
            graph_summary = {
                "channel": persona.get("channel"),
                "channel_reason": (ch_inf or {}).get("reason") or (ch_inf or {}).get("note"),
                "relation_type": persona.get("relation_type"),
                "relation_reason": (rel_inf or {}).get("reason") or (rel_inf or {}).get("note"),
                "age_band": persona.get("age_band"),
                "occupation": persona.get("occupation"),
                "primary_apps": persona.get("primary_apps"),
                "invest_exp": persona.get("invest_exp"),
            }
            path_b_summary = None
            if resp.result_b is not None:
                rb = resp.result_b
                path_b_summary = {
                    "threat_score_100": score01_to_100(getattr(rb, "llm_threat", 0) or 0),
                    "context_score_100": score01_to_100(getattr(rb, "llm_context", 0) or 0),
                    "scam_type": getattr(rb, "scam_type", None),
                }
            elif path_b_note:
                path_b_summary = {"skipped": True, "note": path_b_note}
            narrator_text = run_narrator(
                ra,
                graph_summary=graph_summary,
                model=model,
                base_url=base_url,
                temperature=max(0.1, float(temperature or 0.1)),
                reasons=reasons,
                warnings=warnings,
                gate_score=gate,
                path_b_summary=path_b_summary,
                persona=persona,
            )
        except (OllamaError, Exception) as e:  # noqa: BLE001
            narrator_note = f"Narrator failed: {e}"
            narrator_text = None

    # 把 narrator 寫回 response 物件（Pydantic 允許新實例）
    resp = resp.model_copy(
        update={
            "narrator_text": narrator_text,
            "detail": (resp.detail or "")
            + (f" {narrator_note}" if narrator_note else "")
            + (" Narrator ok." if narrator_text else ""),
        }
    )

    report = analyze_response_to_report(
        resp,
        text=analyze_req.text,
        source=source,
        persona=persona,
        model=model,
        base_url=base_url,
        path_b_note=path_b_note,
    )
    if narrator_note:
        report["narrator_note"] = narrator_note
    return report
