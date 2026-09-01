"""合成訓練樣本（正式訓練集到位前使用）。"""

from __future__ import annotations

from dataclasses import dataclass

from dual_agent.dai.fraud_dual.shared.constants import ScamType


@dataclass(frozen=True)
class SyntheticSample:
    text: str
    scam_type: ScamType
    threat_score: float
    channel: str = "Telegram"
    primary_apps: tuple[str, ...] = ("LINE",)
    age_band: str = "40-59"
    occupation: str = "office"
    relation_type: str = "Unknown"


def build_synthetic_corpus() -> list[SyntheticSample]:
    samples: list[SyntheticSample] = []

    investment = [
        "保證月獲利20%，限時加入投資群，點此下載投資APP https://bit.ly/abc123",
        "內線飆股穩賺不賠，加入Telegram代操群立即開始",
        "虛擬貨幣暴利機會，今天不進場就錯過 https://tinyurl.com/xx",
        "老師帶單獲利驚人，保證報酬率，立刻加LINE",
        "股市當沖密技分享，高報酬投資機會免費領",
    ]
    for t in investment:
        samples.append(SyntheticSample(t, "Investment", 0.88))

    loan = [
        "貸款3000萬，免身分驗證，零利率，保證過件",
        "快速核貸免徵信，信用貸款今天撥款，不用身分證",
        "貸款紓困專案，免審核免擔保，立刻申請",
        "小額貸款高過件率，零利率分期，馬上貸得到",
        "急用錢？免身分貸款，保證過件來電辦理",
    ]
    for t in loan:
        samples.append(SyntheticSample(t, "Loan", 0.86))

    romance = [
        "寶貝想你了，加我交友聊聊，親愛的晚上視訊",
        "寂寞單身交友，寶貝我們戀愛吧，轉帳證明真心",
        "親愛的我遇到困難，麻煩幫我借款救急",
        "交友網站認識你真開心，寶貝可以幫我一點錢嗎",
        "戀愛遊戲開始，親愛的先儲值才能繼續聊",
    ]
    for t in romance:
        samples.append(SyntheticSample(t, "Romance", 0.78, channel="Facebook"))

    fake_cs = [
        "本行客服中心通知：訂單異常請立即退款驗證 https://bank-secure.xyz/login",
        "包裹異常需解除分期，請聯繫官方客服處理",
        "帳戶即將凍結，銀行客服請您點連結完成驗證",
        "警察通知案件，請立即配合客服中心退款流程",
        "訂單異常請回覆驗證碼給客服中心完成退款",
    ]
    for t in fake_cs:
        samples.append(SyntheticSample(t, "Fake_CS", 0.9, channel="SMS"))

    otp = [
        "您的OTP驗證碼為123456，請立刻回覆給客服完成驗證",
        "簡訊驗證碼即將過期，請把手機驗證碼告知對方",
        "動態密碼OTP不要給任何人——請立即回傳驗證碼完成綁定",
        "銀行OTP簡訊驗證，請提供一次性密碼以解除異常",
        "驗證碼已寄出，請馬上告訴我您收到的OTP",
    ]
    for t in otp:
        samples.append(SyntheticSample(t, "OTP_Scam", 0.92, channel="SMS", primary_apps=("SMS", "LINE")))

    job = [
        "高薪日結居家打工，輕鬆賺錢立即招募",
        "兼職幫忙點讚，日結高薪，輕鬆賺錢加LINE",
        "居家打工招募中，高薪不用經驗立刻上班",
        "線上任務日結薪，輕鬆賺錢保證收入",
        "招募助理兼職，高薪日給，立刻報名",
    ]
    for t in job:
        samples.append(SyntheticSample(t, "Job_Scam", 0.8))

    safe = [
        "今晚一起吃飯嗎？老地方見",
        "會議改到明天下午三點，投影片我晚點寄",
        "包裹已送達超商，請記得取件，這是物流通知",
        "媽媽提醒你帶鑰匙，晚上回家吃飯",
        "專案進度正常，下週一把報告交出去即可",
        "這週天氣不錯，週末要不要去爬山",
        "已幫你請假，醫生證明之後補交就好",
        "發票載具歸戶完成，消費明細可在APP查詢",
    ]
    for t in safe:
        samples.append(
            SyntheticSample(
                t,
                "Unknown",
                0.08,
                channel="LINE",
                primary_apps=("LINE",),
                relation_type="Friend",
            )
        )

    # 少量「字典外寫法」逼模型靠文字特徵泛化
    extras = [
        SyntheticSample("免徵信借錢超好過，利率等於零還免證件", "Loan", 0.84),
        SyntheticSample("密訊喊單穩賺翻倍，今晚進場就對了", "Investment", 0.83),
        SyntheticSample("幫我跟客服核對一下訂單，連結在這 http://refund-helper.top/a", "Fake_CS", 0.87),
    ]
    samples.extend(extras)
    return samples
