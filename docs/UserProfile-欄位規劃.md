# User Profile 欄位規劃

> 狀態：設計定案（待實作）  
> 最後更新：2026-09-01  
> 對應模組（現有／規劃）：`dual_agent/cai/profile_store.py`  
> 相關文件：[MessageFeatures-欄位規劃.md](./MessageFeatures-欄位規劃.md)

## 定位

**User Profile 是 Context 的 L3 層（持久事實型 Context）**——見 [Context-分層.md](./Context-分層.md)。

跨輪次保存使用者風險檔案，供 Context Pack 注入、DAI 建圖與 Narrator 個人化。與 **MessageFeatures**（L0 本輪特徵）分工如下：

| 層級 | 生命週期 | 誰維護 | 用途 |
|------|----------|--------|------|
| **L0 MessageFeatures** | 單輪 | NLP | 意圖、正文、關係標籤 |
| **L3 User Profile** | 跨輪次 | App 設定 + 對話寫 relations | 名稱、年齡、relations… |

`remember_relation` / `recall_relation`：NLP（L0）判斷後 **讀寫 L3 Profile**（查表或確認 FSM），不經 Memory LLM。

---

## 使用者看到的五欄位

| # | 欄位（UI） | 說明 | 範例 |
|---|------------|------|------|
| 1 | **名稱** | 使用者或受護者稱呼 | 王小姐、小明 |
| 2 | **年齡** | 實歲或區間 | `68` 或 `60–69` |
| 3 | **職位** | 工作／身份 | 退休、上班族、學生、家管 |
| 4 | **關係** | 親戚、朋友兩類下的重要的人 | 見下節 |
| 5 | **常用 APP** | 常收訊息的 App 多選 | SMS、LINE、Email… |

### 關係（第 4 欄）結構

只分 **兩大類**，其下填 **稱謂 + 姓名**（可多個姓名）：

| 類別 | 稱謂範例 | 姓名範例 |
|------|----------|----------|
| **親戚** | 媽媽、爸爸、兒子、女兒、配偶 | Yuri、小明 |
| **朋友** | 好友、同事（歸朋友類） | Alex |

```json
{
  "名稱": "王小姐",
  "年齡": 68,
  "職位": "退休",
  "關係": {
    "親戚": {
      "媽媽": ["Yuri"],
      "兒子": ["小明"]
    },
    "朋友": {
      "好友": ["Alex"]
    }
  },
  "常用APP": ["SMS", "LINE"]
}
```

---

## API 欄位名（程式用）

| UI 欄位 | API 鍵 | 型別 | 說明 |
|---------|--------|------|------|
| 名稱 | `display_name` | string | |
| 年齡 | `age` | int（1–120） | 送 DAI 前映射 `age_band` |
| 職位 | `job_title` | string | 送 DAI 前映射 `occupation` enum |
| 關係 | `relations` | object | `{ "親戚": {稱謂: 姓名[]}, "朋友": {…} }` |
| 常用 APP | `primary_apps` | string[] | 封閉集合：SMS、LINE、… |

### JSON 骨架（API）

```json
{
  "display_name": "王小姐",
  "age": 68,
  "job_title": "退休",
  "relations": {
    "親戚": {
      "媽媽": ["Yuri"],
      "兒子": ["小明"]
    },
    "朋友": {
      "好友": ["Alex"]
    }
  },
  "primary_apps": ["SMS", "LINE"]
}
```

---

## 內部映射 → DAI `dai_persona`

使用者不可見；由 `profile_store` 在送 DAI 前轉換。

| Profile 來源 | → DAI 欄位 | 規則 |
|--------------|------------|------|
| `age` | `age_band` | `<25` / `25-39` / `40-59` / `60+` |
| `job_title` | `occupation` | student / office / freelance / retired / other（關鍵字或 LLM 對照） |
| `primary_apps` | `primary_apps` | 原樣（已在 ML 封閉集合） |
| `relations` | `known_relations` + `relation_type` | 親戚→Family，朋友→Friend；稱謂對照見 `profile_store._RELATION_TO_CLOSED` |

### 過渡期雙寫

現有四欄 API（`age_band`、`occupation`、`primary_apps`、`invest_exp`）在過渡期 **雙寫相容**；App 新 UI 只暴露五欄，後端負責映射。

---

## 誰可以改哪一欄

| 欄位 | App 設定 | 對話 Memory |
|------|----------|-------------|
| `display_name` | ✅ | ❌ |
| `age` | ✅ | ❌ |
| `job_title` | ✅ | ❌ |
| `relations` | ✅ | ✅（remember / recall / 更正姓名） |
| `primary_apps` | ✅ | ❌ |

**對話 Memory 允許**：在關係下新增／回想／更正姓名（如「我媽媽叫 Yuri」→ 寫入 `親戚.媽媽`）。

**不允許**：用閒聊改名稱、年齡、職位、常用 APP — 引導至 App 設定。

---

## 與 MessageFeatures 的對照

MessageFeatures 的 `social` / `gaps` 與 Profile **讀取或寫入關係**，其餘 Profile 欄位由 Context Pack 帶入 Planner／DAI，不由 NLP 單輪抽取。

| MessageFeatures | Profile | 關係 |
|-----------------|---------|------|
| `social.relation_category` | `relations` 頂層鍵 | `親戚` / `朋友` |
| `social.relation_label` | `relations` 第二層鍵 | 稱謂，如 `媽媽` |
| `social.on_behalf_of_other` | — | 代他人詢問；可結合 `relations` 解讀受護者 |
| `gaps.needs_profile_relation_confirm` | `relations` | 提到稱謂但 Profile 無對應姓名 → `ask_user` 確認 |
| `turn_intent.remember_relation` | `relations` | Memory 短路寫入 |
| `turn_intent.recall_relation` | `relations` | Memory 短路讀取 |

### 範例：代媽媽送審 + Profile 已有媽媽

**Profile**：

```json
{
  "relations": { "親戚": { "媽媽": ["Yuri"] } }
}
```

**本輪 MessageFeatures**（見 MessageFeatures 文件範例）：

- `social.relation_label = "媽媽"`
- `gaps.needs_profile_relation_confirm = false`（Profile 已有對應）

**DAI** 可帶 `known_relations`：`媽媽 → Yuri`，`relation_type`：Family。

---

## 刻意不納入 MVP Profile

| 不放 | 原因 |
|------|------|
| 投資經驗、支付方式、詐騙史等 Tier2 | 已收斂為五欄；日後可「進階設定」 |
| 嗜好、猜職業 | 非防詐 |
| 對話全文 | 屬 Session，非 Profile |

---

## App 設定頁（一頁五欄）

1. **名稱** — 單行文字  
2. **年齡** — 數字或區間選擇器  
3. **職位** — 文字 + 常見標籤（退休／上班族／學生…）  
4. **關係** — 分「親戚｜朋友」兩 Tab，每 Tab 可 + 稱謂 + 姓名  
5. **常用 APP** — 多選 chips（SMS、LINE、Email、Facebook…）  

首次送審可不填滿；Narrator 可提示「完善檔案可讓說明更貼近您」。

---

## 實作備註

- 現有 `profile_store.py` 使用四欄 `age_band / occupation / primary_apps / invest_exp` + `relations` 表；H0 需擴充五欄 schema 與映射。
- Memory intent 限：`remember_*` / `forget` / `recall` / `clarify` / `none`；寫入範圍限 `relations`（必要時 `display_name` 待產品確認）。

---

## 變更紀錄

| 日期 | 說明 |
|------|------|
| 2026-09-01 | 初版：五欄 Profile、DAI 映射、與 MessageFeatures 對照 |
