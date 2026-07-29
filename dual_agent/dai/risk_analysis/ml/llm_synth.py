"""以 LLM（或模板擴寫）合成銀行面風險標註語料。"""

from __future__ import annotations

import hashlib
import json
import random
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.risk_analysis.ml.labels import LabelRecord
from dual_agent.dai.risk_analysis.ml.synthetic_corpus import BENIGN_TEMPLATES, SCAM_TEMPLATES
from dual_agent.llm_json import coerce_llm_text, extract_json_object

# --- 銀行面分桶 ---

BANK_SCAM_BUCKETS: dict[str, dict[str, Any]] = {
    "bank_otp": {
        "desc": "假銀行／假客服索取網銀或信用卡 OTP、動態密碼、驗證碼",
        "fraud_types": ["credential_harvesting", "impersonation"],
        "verdict_gt": "block",
    },
    "bank_password": {
        "desc": "索取網銀帳密、ATM 密碼、登入密碼",
        "fraud_types": ["credential_harvesting", "impersonation"],
        "verdict_gt": "block",
    },
    "bank_card": {
        "desc": "索取信用卡卡號、CVV、有效期限、金融卡資料",
        "fraud_types": ["credential_harvesting", "payment_pressure"],
        "verdict_gt": "block",
    },
    "bank_phish_url": {
        "desc": "假銀行／異常登入驗證釣魚連結（含 http URL）",
        "fraud_types": ["phishing", "impersonation", "malicious_link"],
        "verdict_gt": "block",
    },
    "bank_transfer": {
        "desc": "催匯款、解除凍結需轉帳、假理專要求匯款",
        "fraud_types": ["payment_pressure", "impersonation"],
        "verdict_gt": "block",
    },
    "bank_loan": {
        "desc": "假銀行／假貸款專案、免聯徵核貸話術",
        "fraud_types": ["payment_pressure", "impersonation"],
        "verdict_gt": "warn",
    },
}

BANK_BENIGN_BUCKETS: dict[str, dict[str, Any]] = {
    "bank_official_notify": {
        "desc": "真實風格銀行帳戶異動／消費／入帳通知（絕不索取密碼、OTP、卡號）",
        "fraud_types": [],
        "verdict_gt": "allow",
    },
    "bank_app_alert": {
        "desc": "銀行 App 登入成功、裝置綁定、系統維護等資訊性通知（不索密）",
        "fraud_types": [],
        "verdict_gt": "allow",
    },
    "bank_work_assign": {
        "desc": "銀行相關正常交辦：開官網查匯率、開網銀說明頁等（可含合法 URL，不索密）",
        "fraud_types": [],
        "verdict_gt": "allow",
    },
}

_BANK_NOTE_HINTS = (
    "bank_",
    "password",
    "otp",
    "card_bank",
    "loan",
    "high_risk_combo",
    "low_finance",
    "payment_ransom",
    "bank_notify",
    "bank_maintenance",
    "legit_otp",
)

_BANK_NAMES = (
    "台灣銀行",
    "玉山銀行",
    "國泰世華",
    "中國信託",
    "富邦銀行",
    "兆豐銀行",
    "合作金庫",
    "永豐銀行",
    "台新銀行",
    "第一銀行",
)

_AMOUNTS = (
    "NT$320",
    "NT$500",
    "NT$1,200",
    "NT$3,580",
    "NT$8,000",
    "NT$15,600",
    "NT$50,000",
)

_PHISH_HOSTS = (
    "secure-twbank-login.test",
    "verify-esun-online.test",
    "cathay-unlock.test",
    "ctbc-secure-auth.test",
    "fubon-reset.test",
)

_OFFICIAL_URLS = (
    "https://www.bot.com.tw",
    "https://www.esunbank.com.tw",
    "https://www.cathaybk.com.tw",
    "https://www.ctbcbank.com",
    "https://www.fubon.com",
)


@dataclass(frozen=True)
class SynthItem:
    text: str
    bucket: str
    label: str
    fraud_types: list[str]
    verdict_gt: str


def _norm_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t


def _text_key(text: str) -> str:
    return hashlib.sha256(_norm_text(text).encode("utf-8")).hexdigest()


def _is_bankish_note(note: str) -> bool:
    n = (note or "").lower()
    return any(h in n for h in _BANK_NOTE_HINTS)


def bank_few_shots(bucket: str, *, k: int = 3, rng: random.Random | None = None) -> list[str]:
    """自既有模板抽銀行相關 few-shot。"""
    rng = rng or random.Random(42)
    if bucket in BANK_SCAM_BUCKETS:
        pool = [t for t, note in SCAM_TEMPLATES if _is_bankish_note(note)]
        # 桶偏好
        prefer = {
            "bank_otp": ("otp", "驗證碼"),
            "bank_password": ("password", "密碼"),
            "bank_card": ("card", "卡號", "CVV"),
            "bank_phish_url": ("high_risk", "http"),
            "bank_transfer": ("ransom", "匯款", "轉帳"),
            "bank_loan": ("loan", "貸"),
        }.get(bucket, ())
        ranked = [
            t
            for t in pool
            if any(p.lower() in t.lower() or p in t for p in prefer)
        ] or pool
    else:
        pool = [t for t, note in BENIGN_TEMPLATES if _is_bankish_note(note) or note in ("assistant",)]
        if bucket == "bank_work_assign":
            ranked = [t for t, note in BENIGN_TEMPLATES if note == "assistant" and "http" in t.lower()] or pool
        else:
            ranked = [t for t, note in BENIGN_TEMPLATES if note.startswith("bank") or note == "legit_otp"] or pool
    if not ranked:
        ranked = [t for t, _ in (SCAM_TEMPLATES if bucket.startswith("bank_") and bucket in BANK_SCAM_BUCKETS else BENIGN_TEMPLATES)]
    sample = list(ranked)
    rng.shuffle(sample)
    return sample[: max(1, min(k, len(sample)))]


_SYSTEM = """你是台灣金融防詐語料生成器。只輸出單一 JSON 物件，不要 markdown、不要解說。
JSON 格式：
{"items":[{"text":"簡訊正文","fraud_types":["phishing"]}]}

規則：
1. 繁體中文，像真實簡訊／App 推播口吻。
2. text 之間必須用詞不同，禁止複製 few-shot。
3. 長度約 20–120 字。
4. 若是詐騙：可含急迫、假客服、索密、假連結；fraud_types 從指定清單選。
5. 若是正常：絕對不可索取密碼、OTP、CVV、卡號、身分證；fraud_types 為 []。
6. 僅銀行／金融情境，不要寫物流或政府補助詐騙。"""


def _user_prompt(bucket: str, meta: dict[str, Any], n: int, shots: list[str]) -> str:
    shot_block = "\n".join(f"- {s}" for s in shots)
    ft = meta.get("fraud_types") or []
    return (
        f"領域：銀行（domain=bank）\n"
        f"桶：{bucket}\n"
        f"說明：{meta['desc']}\n"
        f"建議 fraud_types：{json.dumps(ft, ensure_ascii=False)}\n"
        f"請生成恰好 {n} 則。\n"
        f"few-shot（勿照抄）：\n{shot_block}\n"
    )


def _parse_items(raw: str) -> list[dict[str, Any]]:
    obj = extract_json_object(raw)
    items = obj.get("items")
    if not isinstance(items, list):
        raise ValueError("JSON 缺少 items 陣列")
    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        text = _norm_text(str(row.get("text") or ""))
        if len(text) < 8 or len(text) > 240:
            continue
        fts = row.get("fraud_types") or []
        if not isinstance(fts, list):
            fts = []
        out.append({"text": text, "fraud_types": [str(x).strip() for x in fts if str(x).strip()]})
    return out


def invoke_llm_batch(
    *,
    bucket: str,
    meta: dict[str, Any],
    n: int,
    model: str,
    base_url: str,
    temperature: float = 0.85,
    shots: list[str] | None = None,
    invoke_fn: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """呼叫 Ollama 產生一批 items；可注入 invoke_fn 供測試。"""
    shots = shots if shots is not None else bank_few_shots(bucket, k=3)
    user = _user_prompt(bucket, meta, n, shots)

    if invoke_fn is not None:
        return _parse_items(invoke_fn(user))

    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM),
            ("human", "{user}"),
        ]
    )
    chain = prompt | llm | StrOutputParser()

    def _once() -> str:
        return coerce_llm_text(chain.invoke({"user": user}))

    try:
        return _parse_items(_once())
    except ValueError:
        # 重試一次，強調只輸出 JSON
        retry_user = user + "\n請再次輸出，僅一個 JSON 物件。"
        return _parse_items(coerce_llm_text(chain.invoke({"user": retry_user})))


def _allocate(n: int, keys: list[str]) -> dict[str, int]:
    if n <= 0 or not keys:
        return {k: 0 for k in keys}
    base, rem = divmod(n, len(keys))
    out = {k: base for k in keys}
    for i, k in enumerate(keys):
        if i < rem:
            out[k] += 1
    return out


def _assign_splits(records: list[LabelRecord], *, seed: int = 42) -> None:
    rng = random.Random(seed)
    by_label: dict[str, list[LabelRecord]] = {"scam": [], "benign": []}
    for rec in records:
        by_label.setdefault(rec.label, []).append(rec)
    for group in by_label.values():
        rng.shuffle(group)
        n = len(group)
        n_train = int(n * 0.7)
        n_val = int(n * 0.15)
        for i, rec in enumerate(group):
            if i < n_train:
                rec.split = "train"  # type: ignore[misc]
            elif i < n_train + n_val:
                rec.split = "val"  # type: ignore[misc]
            else:
                rec.split = "test"  # type: ignore[misc]


def _to_records(items: list[SynthItem], *, annotator: str) -> list[LabelRecord]:
    return [
        LabelRecord(
            id=str(uuid.uuid4()),
            text=it.text,
            source="synthetic_llm",
            label=it.label,  # type: ignore[arg-type]
            verdict_gt=it.verdict_gt,
            fraud_types_gt=list(it.fraud_types),
            annotator=annotator,
            split="train",
            notes=it.bucket,
        )
        for it in items
    ]


# --- 模板擴寫 fallback（離線可達 600）---

_SCAM_PATTERNS: dict[str, list[str]] = {
    "bank_otp": [
        "【{bank}】帳戶異常，請回傳動態密碼 {otp} 完成驗證",
        "{bank}客服：請提供網銀驗證碼以解除鎖定",
        "您的信用卡交易需 OTP，請立即回覆驗證碼",
        "【安全中心】請將簡訊驗證碼告知專員以續辦",
    ],
    "bank_password": [
        "【{bank}】請回傳網銀帳號密碼完成身分核對",
        "{bank}通知：請提供登入密碼以解除帳戶凍結",
        "因系統升級請回覆您的網路銀行密碼",
        "客服專線：請提供 ATM 密碼完成驗證",
    ],
    "bank_card": [
        "【{bank}】退款需提供卡號與 CVV",
        "請回傳完整信用卡卡號與有效期限",
        "{bank}：請拍照金融卡正反面傳至指定連結",
        "驗證失敗，請提供卡號後三碼安全碼",
    ],
    "bank_phish_url": [
        "【{bank}】帳戶異常請點 https://{host}/login 立即驗證否則凍結",
        "網銀已鎖定，請至 http://{host}/unlock 重設",
        "{bank}安全提示：請登入 https://{host}/verify 更新資料",
        "異常登入偵測，點擊 https://{host}/auth 確認身分",
    ],
    "bank_transfer": [
        "【{bank}】若不立即匯款 {amount} 將法辦",
        "理專通知：請轉帳 {amount} 至指定帳戶解除風險",
        "限時 30 分鐘內匯款，否則帳戶永久停用",
        "已為您保留額度，請先轉帳手續費 {amount}",
    ],
    "bank_loan": [
        "【{bank}專案】免聯徵核貸，加 LINE 申辦",
        "本行可當日撥款，請提供身分資料申貸",
        "低利貸款月息優惠，有意者私訊專員",
        "信用瑕疵可貸，免財力證明請回電",
    ],
}

_BENIGN_PATTERNS: dict[str, list[str]] = {
    "bank_official_notify": [
        "【{bank}】您有一筆 {amount} 入帳，如有疑問請洽官方客服。",
        "{bank}：信用卡消費 {amount}，本行不會索取密碼。",
        "【{bank}】您已成功轉帳 {amount}。",
        "{bank}餘額變動通知：支出 {amount}。",
    ],
    "bank_app_alert": [
        "【{bank} App】登入成功。若非本人操作請致電官方客服。",
        "{bank}：新裝置綁定完成，本行不會請您回傳 OTP。",
        "【{bank}】系統將於凌晨維護，期間暫停轉帳。",
        "{bank}網銀服務已恢復正常。",
    ],
    "bank_work_assign": [
        "請打開 {bank} 官網 {url} 查今日美金匯率後回報。",
        "幫我開 {url} 看{bank}網銀說明頁，整理開戶步驟。",
        "查一下 {bank} 信用卡權益，參考 {url}",
        "請到 {url} 下載{bank}官方 App 安裝說明（勿輸入密碼給我）。",
    ],
}


def expand_bank_templates(
    *,
    n_scam: int,
    n_benign: int,
    seed: int = 42,
) -> list[SynthItem]:
    """不依賴 LLM，以槽位擴寫產生銀行面語料。"""
    rng = random.Random(seed)
    seen: set[str] = set()
    items: list[SynthItem] = []
    serial = 0

    def _fill(patterns: list[str]) -> str:
        nonlocal serial
        serial += 1
        pat = rng.choice(patterns)
        text = pat.format(
            bank=rng.choice(_BANK_NAMES),
            amount=rng.choice(_AMOUNTS),
            host=rng.choice(_PHISH_HOSTS),
            url=rng.choice(_OFFICIAL_URLS),
            otp=f"{rng.randint(100000, 999999)}",
        )
        # 序號後綴提高去重空間（仍保持可讀）
        if serial % 3 == 0:
            text = f"{text}（案件編號 {serial:04d}）"
        elif serial % 3 == 1:
            text = f"{text} 編號{serial}"
        return text

    scam_alloc = _allocate(n_scam, list(BANK_SCAM_BUCKETS.keys()))
    for bucket, need in scam_alloc.items():
        meta = BANK_SCAM_BUCKETS[bucket]
        patterns = _SCAM_PATTERNS[bucket]
        tries = 0
        while sum(1 for x in items if x.bucket == bucket) < need and tries < need * 40:
            tries += 1
            text = _norm_text(_fill(patterns))
            key = _text_key(text)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                SynthItem(
                    text=text,
                    bucket=bucket,
                    label="scam",
                    fraud_types=list(meta["fraud_types"]),
                    verdict_gt=str(meta["verdict_gt"]),
                )
            )

    benign_alloc = _allocate(n_benign, list(BANK_BENIGN_BUCKETS.keys()))
    for bucket, need in benign_alloc.items():
        meta = BANK_BENIGN_BUCKETS[bucket]
        patterns = _BENIGN_PATTERNS[bucket]
        tries = 0
        while sum(1 for x in items if x.bucket == bucket) < need and tries < need * 40:
            tries += 1
            text = _norm_text(_fill(patterns))
            key = _text_key(text)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                SynthItem(
                    text=text,
                    bucket=bucket,
                    label="benign",
                    fraud_types=[],
                    verdict_gt="allow",
                )
            )

    return items


def generate_bank_corpus(
    *,
    n_scam: int = 300,
    n_benign: int = 300,
    model: str | None = None,
    base_url: str | None = None,
    batch_size: int = 8,
    seed: int = 42,
    use_llm: bool = True,
    invoke_fn: Callable[[str], str] | None = None,
) -> list[LabelRecord]:
    """
    產生銀行面標註。
    use_llm=True：依桶呼叫 LLM，不足時以模板擴寫補齊。
    use_llm=False：純模板擴寫。
    """
    rng = random.Random(seed)
    model = model or OLLAMA_MODEL
    base_url = base_url or OLLAMA_BASE_URL
    seen: set[str] = set()
    collected: list[SynthItem] = []

    def _accept(it: SynthItem) -> bool:
        key = _text_key(it.text)
        if key in seen:
            return False
        seen.add(key)
        collected.append(it)
        return True

    if use_llm:
        scam_alloc = _allocate(n_scam, list(BANK_SCAM_BUCKETS.keys()))
        for bucket, need in scam_alloc.items():
            meta = BANK_SCAM_BUCKETS[bucket]
            got = 0
            rounds = 0
            while got < need and rounds < max(8, (need // batch_size) + 5):
                rounds += 1
                ask = min(batch_size, need - got)
                try:
                    rows = invoke_llm_batch(
                        bucket=bucket,
                        meta=meta,
                        n=ask,
                        model=model,
                        base_url=base_url,
                        shots=bank_few_shots(bucket, k=3, rng=rng),
                        invoke_fn=invoke_fn,
                    )
                except Exception:
                    break
                for row in rows:
                    fts = row["fraud_types"] or list(meta["fraud_types"])
                    if _accept(
                        SynthItem(
                            text=row["text"],
                            bucket=bucket,
                            label="scam",
                            fraud_types=fts,
                            verdict_gt=str(meta["verdict_gt"]),
                        )
                    ):
                        got += 1
                        if got >= need:
                            break

        benign_alloc = _allocate(n_benign, list(BANK_BENIGN_BUCKETS.keys()))
        for bucket, need in benign_alloc.items():
            meta = BANK_BENIGN_BUCKETS[bucket]
            got = 0
            rounds = 0
            while got < need and rounds < max(8, (need // batch_size) + 5):
                rounds += 1
                ask = min(batch_size, need - got)
                try:
                    rows = invoke_llm_batch(
                        bucket=bucket,
                        meta=meta,
                        n=ask,
                        model=model,
                        base_url=base_url,
                        shots=bank_few_shots(bucket, k=3, rng=rng),
                        invoke_fn=invoke_fn,
                    )
                except Exception:
                    break
                for row in rows:
                    if _accept(
                        SynthItem(
                            text=row["text"],
                            bucket=bucket,
                            label="benign",
                            fraud_types=[],
                            verdict_gt="allow",
                        )
                    ):
                        got += 1
                        if got >= need:
                            break

    scam_have = sum(1 for x in collected if x.label == "scam")
    benign_have = sum(1 for x in collected if x.label == "benign")
    need_scam = max(0, n_scam - scam_have)
    need_benign = max(0, n_benign - benign_have)
    if need_scam or need_benign:
        for it in expand_bank_templates(n_scam=need_scam, n_benign=need_benign, seed=seed + 7):
            _accept(it)

    # 若仍不足（極端碰撞），再擴一輪
    scam_have = sum(1 for x in collected if x.label == "scam")
    benign_have = sum(1 for x in collected if x.label == "benign")
    if scam_have < n_scam or benign_have < n_benign:
        for it in expand_bank_templates(
            n_scam=max(0, n_scam - scam_have) + 50,
            n_benign=max(0, n_benign - benign_have) + 50,
            seed=seed + 99,
        ):
            _accept(it)
            if sum(1 for x in collected if x.label == "scam") >= n_scam and sum(
                1 for x in collected if x.label == "benign"
            ) >= n_benign:
                break

    scam_items = [x for x in collected if x.label == "scam"][:n_scam]
    benign_items = [x for x in collected if x.label == "benign"][:n_benign]
    records = _to_records(
        scam_items + benign_items,
        annotator="llm_synth_bank_v1" if use_llm else "template_expand_bank_v1",
    )
    _assign_splits(records, seed=seed)
    return records
