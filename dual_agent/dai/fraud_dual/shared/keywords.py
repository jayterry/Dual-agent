"""關鍵字詞典（規則抽取用；可後續改為外部 JSON）。"""

from __future__ import annotations

RHETORIC: dict[str, list[str]] = {
    "urgency": [
        "立即",
        "馬上",
        "立刻",
        "今天截止",
        "今日截止",
        "30分鐘內",
        "最後機會",
        "限時",
        "盡快",
        "逾期",
    ],
    "authority": [
        "銀行",
        "客服",
        "警察",
        "法院",
        "主管",
        "老師",
        "官方",
        "本行",
        "警察局",
        "金管會",
    ],
    "reward": [
        "保證獲利",
        "高報酬",
        "中獎",
        "回饋",
        "免費",
        "月獲利",
        "穩賺",
        "暴利",
        "紅利",
        "領獎",
    ],
    "fear": [
        "停權",
        "凍結",
        "違規",
        "異常登入",
        "帳號停用",
        "即將關閉",
        "報警",
        "起訴",
        "扣款",
        "帳戶異常",
    ],
}

OBFUSCATION_PATTERNS: list[str] = [
    r"微\s*\*+\s*信",
    r"\bVX\b",
    r"L\s*-\s*I\s*-\s*N\s*-\s*E",
    r"TG群",
    r"薇信",
    r"加[\s　]*[VvＶ]",
]

INTENT_KEYWORDS: dict[str, list[str]] = {
    "investment_keyword": [
        "股票",
        "投資",
        "飆股",
        "代操",
        "獲利",
        "當沖",
        "虛擬貨幣",
        "加密貨幣",
        "理財群",
    ],
    "otp_keyword": [
        "OTP",
        "otp",
        "驗證碼",
        "手機驗證",
        "簡訊驗證",
        "一次性密碼",
        "動態密碼",
    ],
    "loan_keyword": [
        "貸款",
        "快速核貸",
        "保證過件",
        "信用貸款",
        "借貸",
        "紓困",
    ],
    "romance_keyword": [
        "交友",
        "戀愛",
        "寶貝",
        "親愛的",
        "想你",
        "孤寂",
    ],
    "customer_service_keyword": [
        "解除分期",
        "客服中心",
        "訂單異常",
        "退款",
        "假客服",
        "包裹異常",
    ],
    "job_keyword": [
        "高薪",
        "日結",
        "居家打工",
        "輕鬆賺錢",
        "招募",
        "兼职",
        "兼職",
    ],
}

SHORTENERS: tuple[str, ...] = (
    "bit.ly",
    "tinyurl.com",
    "reurl.cc",
    "goo.gl",
    "t.co",
    "shorturl.at",
    "cutt.ly",
)

SUSPICIOUS_TLDS: tuple[str, ...] = (
    ".top",
    ".vip",
    ".click",
    ".xyz",
    ".icu",
    ".work",
    ".gq",
    ".tk",
)

APK_HINTS: tuple[str, ...] = (
    "下載app",
    "下載應用",
    "下載 apk",
    ".apk",
    "安裝app",
    "安裝應用",
    "點此下載",
    "下載投資",
)

OUTSIDE_STORE_HINTS: tuple[str, ...] = (
    "外部連結",
    "官方商店以外",
    "非play商店",
    "非app store",
    "側載",
    "傳輸檔案安裝",
)

HIGH_RISK_PERMISSIONS: tuple[str, ...] = (
    "sms",
    "簡訊",
    "聯絡人",
    "通訊錄",
    "無障礙",
    "accessibility",
    "裝置管理員",
    "覆蓋",
    "悬浮窗",
    "懸浮窗",
    "讀取簡訊",
)

# Channel 先驗風險（可調）
CHANNEL_PRIOR_RISK: dict[str, float] = {
    "LINE": 0.15,
    "Telegram": 0.55,
    "SMS": 0.45,
    "Email": 0.35,
    "Facebook": 0.40,
    "Website": 0.50,
}
