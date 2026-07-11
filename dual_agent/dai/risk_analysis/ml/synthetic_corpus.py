"""模擬標註語料：多類型詐騙／正常訊息模板。"""

from __future__ import annotations

# (text, fraud_type_or_note)
SCAM_TEMPLATES: list[tuple[str, str]] = [
    # password / credentials
    ("請立即驗證您的網路銀行密碼並回傳", "password_credentials"),
    ("您的銀行帳戶異常，請回傳登入密碼以解除鎖定", "password_credentials"),
    ("客服通知：請提供網銀帳號密碼完成身分核對", "password_credentials"),
    ("因安全升級，請回覆您的使用者密碼", "password_credentials"),
    ("帳戶將於今日凍結，請立即回傳密碼驗證", "password_credentials"),
    ("請將 Facebook 帳號密碼傳至本號碼完成申訴", "password_credentials"),
    ("您的 Email 密碼已外洩，請回傳新密碼", "password_credentials"),
    ("為保護帳戶請提供 ATM 網銀密碼", "password_credentials"),
    # otp
    ("您的驗證碼為 123456，請勿告知他人", "otp"),
    ("簡訊驗證碼 887766 請回傳以完成交易", "otp"),
    ("OTP 654321 請在 5 分鐘內告知客服", "otp"),
    ("動態密碼 442211 請勿告訴任何人", "otp"),
    ("您的手機驗證碼是 998877，請立即回覆", "otp"),
    ("銀行動態碼 556677 請提供給專員", "otp"),
    ("登入驗證碼 334455 請回傳", "otp"),
    ("一次性密碼 112233 請勿外洩給他人", "otp"),
    # card / bank
    ("請提供信用卡卡號與金融卡後三碼", "card_bank_sensitive"),
    ("請回傳完整 16 碼卡號與有效期限", "card_bank_sensitive"),
    ("因退款需要，請提供銀行卡號與 CVV", "card_bank_sensitive"),
    ("請拍照信用卡正反面傳至 LINE", "card_bank_sensitive"),
    ("帳戶驗證需金融卡號與戶名", "card_bank_sensitive"),
    ("請提供提款卡卡號與密碼", "card_bank_sensitive"),
    # national id
    ("請回傳身分證字號與統一編號以完成認證", "national_id_ubn"),
    ("實名制需要您的身分證正反面照片", "national_id_ubn"),
    ("請提供健保卡號與身分證字號", "national_id_ubn"),
    ("補助申請請回傳身分證與戶籍地址", "national_id_ubn"),
    ("公司登記需負責人身分證與統編", "national_id_ubn"),
    # payment pin
    ("請輸入 LINE Pay 交易密碼完成驗證", "local_payment_pin"),
    ("街口支付 PIN 碼請回傳以解鎖帳戶", "local_payment_pin"),
    ("請提供悠遊付支付密碼", "local_payment_pin"),
    ("Apple Pay 驗證需交易密碼", "local_payment_pin"),
    ("請回傳電子支付 6 碼密碼", "local_payment_pin"),
    # ransom / payment pressure
    ("若不匯款將對您不利，請立即轉帳", "payment_ransom_threat"),
    ("限時 30 分鐘內匯款否則提告", "payment_ransom_threat"),
    ("已掌握您的資料，不付款就公開", "payment_ransom_threat"),
    ("請立即轉帳 5 萬元至指定帳戶", "payment_ransom_threat"),
    ("逾期將加收罰金，請馬上匯款", "payment_ransom_threat"),
    ("不匯款將通知您公司主管", "payment_ransom_threat"),
    # physical threat
    ("我知道你家地址，不付款就對你不利", "physical_threat"),
    ("已派人至您住處，請立即匯款", "physical_threat"),
    ("若不配合將對您家人不利", "physical_threat"),
    ("我們的人在您樓下，請馬上轉帳", "physical_threat"),
    # high risk combo + url
    ("您的帳戶異常請點擊 https://evil.test 立即驗證否則凍結", "high_risk_combo"),
    ("帳戶將停用請點 http://fake-bank.test/login 完成驗證", "high_risk_combo"),
    ("異常登入請至 https://secure-verify.test 重設密碼", "high_risk_combo"),
    ("點擊 https://phish.example/pay 補繳欠款否則法辦", "high_risk_combo"),
    ("您的網銀已鎖定 https://unlock.test 立即處理", "high_risk_combo"),
    ("限時驗證 https://urgent.test 否則帳戶凍結", "high_risk_combo"),
    ("帳號異常 https://help-desk.test 請輸入卡號", "high_risk_combo"),
    ("【銀行】請點 https://tw-bank-fake.test 更新資料", "high_risk_combo"),
    # loan scams
    ("免擔保免聯徵月息 0.18%，有意者請洽", "loan_scam"),
    ("健保卡可借款 50 萬，手續費全免", "nh_card_loan"),
    ("本行可核貸 200 萬，請加 LINE 詳談", "unsolicited_loan_pitch"),
    ("低利貸款當日撥款，加賴 ID: loan888", "loan_scam"),
    ("無抵押信貸核准，請加微信洽談", "unsolicited_loan_pitch"),
    ("勞保資料可貸 80 萬，手續費先付", "loan_scam"),
    ("信用瑕疵可貸，加 LINE loan-fast", "loan_scam"),
    ("免財力證明貸款，請提供身分證", "loan_scam"),
    ("農會專案核貸 100 萬，請回電", "nh_card_loan"),
    ("保單質押可借 60 萬，當日撥款", "loan_scam"),
    ("學生專案低利貸款，加 LINE 申請", "unsolicited_loan_pitch"),
    ("週轉金專案，無需聯徵，有意私訊", "loan_scam"),
    # identity framework
    ("政府補助實名認證，請填寫資料", "identity_scam_framework"),
    ("健保局通知：請完成實名認證否則停權", "identity_scam_framework"),
    ("國稅局退稅需實名驗證，請點連結", "identity_scam_framework"),
    ("勞保局補助請填寫個人資料", "identity_scam_framework"),
    ("監理站通知需線上實名，請回傳資料", "identity_scam_framework"),
    ("戶政系統升級請重新認證身分", "identity_scam_framework"),
    # low finance notify (ambiguous)
    ("您的帳戶驗證失敗，請立即處理", "low_finance_notify"),
    ("【銀行】您有一筆異常交易請回覆", "low_finance_notify"),
    ("帳戶安全提醒：請盡快完成驗證", "low_finance_notify"),
    ("您的信用卡有可疑消費請聯繫", "low_finance_notify"),
    ("網銀登入異常，請立即確認", "low_finance_notify"),
    ("【通知】款項未能入帳請處理", "low_finance_notify"),
    # logistics phishing
    ("【順豐】包裹異常請點連結補繳運費 https://phish.example/x", "logistics_phish"),
    ("【黑貓】配送失敗請點 https://delivery-fake.test 重寄", "logistics_phish"),
    ("【7-11】包裹待補費用 https://pay-parcel.test", "logistics_phish"),
    ("【郵局】郵件遭退件請點連結處理", "logistics_phish"),
    ("快遞通知：運費未付請立即繳納", "logistics_phish"),
    ("您的包裹含違禁品請聯繫客服加 LINE", "logistics_phish"),
    # investment
    ("投資飆股老師 LINE 帶單穩賺", "investment_scam"),
    ("內線消息飆股，加群組跟單", "investment_scam"),
    ("虛擬貨幣穩賺方案，先入金", "investment_scam"),
    ("保證獲利投資群，請加 LINE", "investment_scam"),
    ("外匯老師帶單，月入 30%", "investment_scam"),
    ("股票診斷加 LINE，穩賺不賠", "investment_scam"),
]

BENIGN_TEMPLATES: list[tuple[str, str]] = [
    # logistics (legitimate)
    ("您的包裹已送達 7-11 門市，請於三日內領取。", "logistics"),
    ("包裹已配達，感謝使用本服務。", "logistics"),
    ("黑貓宅急便：商品已送達管理室。", "logistics"),
    ("順豐快遞：快件已簽收，感謝使用。", "logistics"),
    ("您的訂單 #12345 已出貨", "ecommerce"),
    ("蝦皮訂單已出貨，預計明日送達。", "ecommerce"),
    ("momo 訂單配送中，請留意簡訊。", "ecommerce"),
    ("PChome 訂單已出貨，物流單號 12345678", "ecommerce"),
    # banking (informational, no credential harvest)
    ("台灣銀行：您有一筆 NT$500 入帳，如有疑問請洽客服。", "bank_notify"),
    ("玉山銀行：您的帳戶餘額變動通知。", "bank_notify"),
    ("國泰世華：信用卡消費 NT$320 元。", "bank_notify"),
    ("中信銀行：您已成功轉帳 NT$1000。", "bank_notify"),
    ("銀行公告：系統將於凌晨維護，期間無法轉帳。", "bank_maintenance"),
    ("富邦銀行：網銀服務已恢復正常。", "bank_maintenance"),
    # work / meeting
    ("明天下午三點團隊會議，地點在三樓會議室。", "work"),
    ("會議邀請：週五 10:00 Google Meet", "work"),
    ("請於週一前提交週報。", "work"),
    ("下午兩點與客戶開會，請準時。", "work"),
    ("專案進度會議改至四樓。", "work"),
    ("HR 通知：下週一為國定假日。", "work"),
    # assistant / search
    ("搜尋台北今天天氣，再幫我開 https://github.com", "assistant"),
    ("高雄今天天氣如何？", "assistant"),
    ("請幫我開啟 Google 首頁", "assistant"),
    ("查詢台中即時天氣", "assistant"),
    ("幫我搜尋附近的咖啡廳", "assistant"),
    ("開啟 https://stackoverflow.com 查 Python 錯誤", "assistant"),
    ("請整理本週行事曆", "assistant"),
    ("提醒我明天早上九點開會", "assistant"),
    # general / chat
    ("今天氣溫 25 度，午後可能有雨。", "general"),
    ("請記得帶便當，謝謝。", "general"),
    ("您好，這是測試通知，無需回覆。", "general"),
    ("午餐要吃什麼？", "general"),
    ("下班一起走路回家嗎？", "general"),
    ("週末有空看電影嗎？", "general"),
    ("會議室冷氣太強，記得帶外套。", "general"),
    ("文件已放在共用資料夾。", "general"),
    # legitimate verification context
    ("驗證碼僅供您本人登入官方 App 使用（台灣大哥大）。", "legit_otp"),
    ("您的 Google 兩步驟驗證碼，請勿分享給他人。", "legit_otp"),
    ("銀行 App 登入驗證碼，本行不會主動索取。", "legit_otp"),
    ("官方客服不會索取密碼，請提高警覺。", "security_tip"),
    # utilities / government info (non-scam)
    ("台電：本期電費帳單已寄出，詳見官網。", "utility"),
    ("自來水費已可線上繳納。", "utility"),
    ("健保署：請至官網查詢補助資格，勿點陌生連結。", "gov_info"),
    ("國稅局：綜所稅申報期間請使用官方網站。", "gov_info"),
    # transport
    ("高鐵訂票成功，車次 123 台北 08:30。", "transport"),
    ("Uber 行程已完成，感謝搭乘。", "transport"),
    ("YouBike 還車成功。", "transport"),
    # food / daily
    ("外送訂單已送達，請至大門口取餐。", "food"),
    ("餐廳訂位確認：今晚七點兩位。", "food"),
    # tech notifications
    ("GitHub：您的 PR 已被合併。", "tech"),
    ("Slack：您在 #general 被提及。", "tech"),
    ("Google 日曆：15 分鐘後有會議。", "tech"),
    # customer service (benign)
    ("客服：您的問題已收到，將於 1 個工作天回覆。", "support"),
    ("退貨申請已受理，請留意物流。", "support"),
    # more benign with URLs (trusted)
    ("請參考官方文件 https://docs.python.org", "assistant"),
    ("公司內網 https://intranet.company.local 已更新。", "work"),
    ("下載安裝檔：https://releases.microsoft.com", "tech"),
]
