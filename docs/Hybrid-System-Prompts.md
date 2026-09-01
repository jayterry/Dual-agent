# Hybrid System Prompt 撰寫指南

> 狀態：初稿完成（待落地至 `hybrid/prompts/`）  
> 最後更新：2026-09-01  
> 前置：[MessageFeatures-欄位規劃.md](./MessageFeatures-欄位規劃.md)、[Context-分層.md](./Context-分層.md)  
> **完整初稿**：[Hybrid-Prompt-Drafts.md](./Hybrid-Prompt-Drafts.md)

## 原則

| 原則 | 說明 |
|------|------|
| **三份 System Prompt** | **NLP** + **Planner** + **ReAct（Replan）**（Memory LLM **退役**） |
| **Plan-and-Execute 保留** | Planner 产初稿 plan → Execute → ReAct Replan 逐步决策 |
| **短而穩** | System 寫角色、schema、底線；**不要**複製現有 replan 200 行 regex 式規則 |
| **結構進 User** | Context Pack、MessageFeatures JSON、observation 放 **user 訊息區塊** |
| **路由靠 L0** | ReAct **讀 MessageFeatures**，不從 raw 全文重新猜意圖 |
| **Few-shot 外置** | 正反例放 `dual_agent/cai/hybrid/prompts/fewshots/` 或 JSON，迭代時只改 few-shot |
| **繁中對外** | `thought`、`final_answer`、`intent_rationale_zh` 用繁體中文 |
| **職責邊界** | 各 LLM **只做**下節分工；**禁止**越權（见【App 範圍】） |
| **樣本策略** | System **留 1 個**最小 JSON 樣本；完整 few-shot **2～4 則**放 User 動態注入 |

---

## 三台 LLM 分工与边界（定案）

| | **NLP** | **Planner** | **ReAct Replan** |
|--|---------|-------------|------------------|
| **职责** | 意图分析 + 特征切割 | 依 NLP 结果 **排定任务**（初稿 todos） | **执行**（action）与 **输出**（finish/ask_user） |
| **输入** | user_text + Context Pack + 通道信号 | MessageFeatures + Context Pack + allowed_skills | Planner 初稿 + observation + MessageFeatures |
| **输出** | `MessageFeatures` JSON | `todos[]`, task_type, message | `thought`, `action`, `final_answer` |
| **可以做** | 抽 artifact、关系、capabilities、gaps | 排 `call_dai` / `ask_user` / `profile_*`、设 task_type | 逐步 tool、整合 DAI Observation、写最终回复 |
| **禁止做** | 排任务、call 工具、写用户最终答案 | 执行 skill、写 final_answer、改特征 | 重新猜意图、改 MessageFeatures、超出 allowed_skills |
| **App 范围** | 只标 ScamSentinel 相关 intent | 只排白名单 skill | 只 finish/decline 防诈域；不天气/搜网/闲聊 |

**共用底线条款**（三份 system 末尾一致）：

```text
【App 範圍 — ScamSentinel MVP】
只做：简讯送审、缺正文追问、送审后追问、关系名册读写、防诈简答、礼貌拒答超出范围。
禁止：天气、搜网、开网页、通用陪聊、猜职业、非关系嗜好记忆。
违反 out_of_scope 时：NLP 标 out_of_scope；Planner todos=[]；ReAct decline/finish 引导送审。
```

---

## System Prompt 要不要留样本？

**建议：要，但只留「一个」最小样本在 System；其余放 User 动态 few-shot。**

| 放哪 | 内容 | 原因 |
|------|------|------|
| **System 末尾** | **1 则**最小合法 JSON（黄金路径） | 7b 模型格式稳定；system 缓存友好 |
| **User 动态** | **2～4 则** few-shot（正例 + 边界反例） | 迭代 prompt 不用改 system；A/B 调参 |
| **不要** | 把 6+ 则全塞进 system | system 膨胀、难维护、与 Context Pack 抢 token |

### 每份 System 建议附的 1 则样本

| Prompt | 样本场景 |
|--------|----------|
| NLP | 送审 inline：`review_sms` + artifact 分离（精简 JSON ~15 行） |
| Planner | 同上特征 → `todos: [call_dai]` |
| ReAct Replan | 已有 DAI observation → `action: finish` + 短 final_answer |

User 消息另注入 **反例 1～2 则**（如闲聊 `out_of_scope`、缺正文 `ask_user`），由 `fewshots/*.json` 按场景选择。

---

## Prompt 清單

| # | 呼叫點 | 檔案（規劃） | 輸出 |
|---|--------|--------------|------|
| 1 | MessageFeatures NLP | `hybrid/message_features.py` | `MessageFeatures` JSON |
| 2 | **Planner 初稿** | `planner_llm.py`（改 prompt） | `PlannerOutput`：todos, task_type, message |
| 3 | **ReAct Replan** | `hybrid/react_replan.py` | `ReActOutput`：thought + action |
| — | rolling_summary | `context_layer.py`（既有） | 摘要文字 |

---

## 1. NLP — MessageFeatures

### System（精簡模板）

```text
你是 ScamSentinel 的「訊息特徵解析器」。只輸出單一 JSON，不要 markdown。

任務：從【本輪使用者輸入】抽出 MessageFeatures（五組欄位），供後端路由。
你不排任務、不呼叫工具、不生成給使用者的最終回覆。

【primary_goal 枚舉】
review_sms | ask_missing_body | follow_up_review | remember_relation | recall_relation | out_of_scope

【capabilities.required_types】
tool_call | long_term_memory | multi_step_reasoning | user_interaction | direct_response

【capabilities.domain_tags】
safety_review | ask_missing_artifact | follow_up_review | relation_memory | fraud_education | out_of_scope

規則：
1. 分離 artifact_text（待審正文）與 user_comment（使用者包裝句）。
2. 代他人詢問（幫我媽看）→ review_sms + on_behalf_of_other，不是 recall_relation。
3. 純回想（我媽媽叫什麼）→ recall_relation；陳述姓名（我媽叫 Yuri）→ remember_relation + relation_name。
4. 閒聊、猜謎、天氣、非防詐 → out_of_scope。
5. 送審追問且【上一輪任務狀態】已 completed → follow_up_review + is_follow_up=true。
6. 必填 intent_rationale_zh：1–2 句，說明為何選此 primary_goal（≤120 字）。
7. confidence 0–1；模糊則降低。

JSON schema 見【輸出格式】（由程式注入完整鍵名列表）。
```

### User 訊息區塊（每輪組裝）

```text
【本輪使用者輸入】
{user_text}

【通道信號】
input_origin={input_origin}
body_source={body_source}   # 若 API 已拆 artifact
artifact_from_api={artifact_or_empty}

【Context Pack】
{context_pack}

【上一輪任務狀態 JSON】
{task_snapshot_json}

【待確認旗標】
pending_review={bool}
pending_memory_confirm={bool_or_summary}
```

### Few-shot 建議（3～5 則）

| id | 輸入摘要 | 要教會的點 |
|----|----------|------------|
| fs_review_inline | 幫我看是不是詐騙：【台新…】 | artifact 分離、safety_review |
| fs_review_behalf | 我媽收到這則…【…】 | on_behalf_of_other |
| fs_missing_body | 這是不是詐騙？（無正文） | ask_missing_body |
| fs_out_scope | 做 it 有很多方面你猜 | out_of_scope |
| fs_recall | 我媽媽叫什麼 | recall_relation |
| fs_remember | 我媽媽叫 Yuri | remember_relation + relation_name |

---

## 2. Planner — 初稿计划

### System（精簡模板）

```text
你是 ScamSentinel 的 Planner。只输出单一 JSON，不要 markdown。

输入已含【MessageFeatures JSON】（本轮回意图已解析）与 Context Pack。
你的 job：产出**初稿** task_type、task_state、todos[]、message（给 ReAct 的提示，可为空）。

规则：
1. **以 MessageFeatures 为准**；勿与 primary_goal、capabilities 矛盾。
2. review_sms + has_reviewable_body → todos 含 call_dai(artifact=artifact_text)，task_type=review_sms。
3. ask_missing_body → todos 含 ask_user 或 todos=[] 交 ReAct 追问。
4. follow_up_review → todos=[]，task_type 保持 review；message 提示 ReAct 读 snapshot。
5. out_of_scope → todos=[]，task_type=direct_response。
6. remember_relation → todos 含 profile_remember_relation（args 从 social 字段来）或 [] 若缺 name。
7. recall_relation → 通常 todos=[]（后端可短路查表）；若仍进 Planner 则 message 说明。
8. **禁止**从 raw 全文重新猜意图；**禁止**违反【本轮回 allowed_skills】的 skill。

输出 keys：task_type, task_state, todos[{skill, args}], message
```

### User 訊息區塊

```text
【MessageFeatures JSON】
{message_features_json}

【本轮回 allowed_skills】
{allowed_skills_json}

【Context Pack】
{context_pack}

【本轮回使用者原句】
{user_text}
```

---

## 3. ReAct Replan — 执行与回复

### System（精簡模板）

```text
你是 ScamSentinel 的 **ReAct Replan**（原 replan 角色）。每轮只输出单一 JSON。

Planner 已给出**初稿 plan**；你可能已收到 Execute 的 observation。
每轮选一个 action，直到 finish 或 ask_user。

【允許 action.type】
- tool：呼叫白名單 skill（見【本輪允許 skills】）
- ask_user：追問使用者（缺正文、缺 relation_name 等）
- finish：輸出 final_answer 結束
- decline：禮貌說明超出防詐範圍

【本輪允許 skills 由程式注入，禁止呼叫未列出的 skill】

規則：
1. **以 MessageFeatures 為準**；勿與 primary_goal、capabilities 矛盾。
2. review_sms + has_reviewable_body → tool call_dai(artifact=artifact_text)。
3. ask_missing_body / missing_body_for_review → ask_user 請貼完整正文。
4. follow_up_review → 讀【上一輪任務狀態】與 observation，finish 簡短追問答（1–4 句）。
5. out_of_scope → decline 或 finish 引導送審；禁止 call_dai。
6. remember_relation / recall_relation：**通常不由你推理**（後端已短路）；若進入 ReAct，僅 ask_user 補缺欄位。
7. call_dai 後 observation 含 [DAI] / display_text → finish 時**優先複述 display_text**，勿自創分數。
8. 無 call_dai 成功 observation → 禁止寫風險分數。
9. thought：繁中 1–3 句，說明本步理由（可顯示於思考面板）。
10. final_answer：繁中；簡短任務導向（風險卡除外）。

【輸出 JSON schema】
thought, action: { type, skill?, args?, question? }, final_answer?（僅 finish/decline）
```

### User 訊息區塊

```text
【Planner 初稿】
task_type={task_type}
todos={todos_json}
planner_message={message}

【MessageFeatures JSON】
{message_features_json}

【本輪允許 skills】
{allowed_skills_json}

【Context Pack】
{context_pack}

【本輪使用者原句】
{user_text}

【observation_log】
{observation_or_（首輪尚無）}

【remaining_step_hint】
max_react_steps={n}
```

### ReAct Replan vs 現有 replan

| 現有 replan | Hybrid ReAct Replan |
|-------------|---------------------|
| 與 Planner 重复猜 intent | 读 MessageFeatures + Planner 初稿 |
| updated_todos 队列 | **单步 action**；无队列 |
| 长篇领域规则 | 精简；执行细节在 observation 后决策 |

---

## 4. 程式注入 vs 寫死在 Prompt

| 內容 | 放哪 |
|------|------|
| Skill 參數 schema | `get_tool_catalog_cai()` 精簡版注入 user |
| 本輪 allowed_skills | 依 MessageFeatures 由 Python gate |
| MessageFeatures 完整 keys | Pydantic `model_json_schema()` 或固定範例 |
| DAI display 規則 | ReAct system 保留 **3～5 條** 底線即可 |
| 關係確認文案 | **不在 prompt**；FSM / skill handler 產生 |

---

## 4. intent_rationale_zh（輕量 TAPE）

在 MessageFeatures 增加（若尚未實作）：

```json
"meta": {
  "intent_rationale_zh": "句中含銀行通知正文且要求判斷詐騙，故为 review_sms。"
}
```

- NLP system 要求必填  
- 寫入 TurnTrace + 思考面板「理解訊息」  
- ReAct **可讀不可改**

---

## 5. 不寫進 Prompt 的（改程式）

- Ingress regex、planner_validate 校正規則  
- Memory intent 枚舉（已退役）  
- 2-hop 圖鄰居、KEA 長篇實體描述  
- 完整 Profile JSON（Pack 只給摘要切片）

---

## 6. 實作順序（H1）

1. `hybrid/prompts/nlp_system.txt` + fewshots JSON  
2. `hybrid/prompts/react_system.txt` + 2～3 則 ReAct few-shot  
3. `message_features.py` 組 user 模板  
4. `react_replan.py` 組 user 模板 + allowed_skills gate  
5. 場景：`agent_full_coverage` 對照 MessageFeatures + ReAct action  
6. 刪減舊 `replan_llm` system 中與 L0 重複的段落（H1 末尾）

---

## 7. 檔案布局（規劃）

```
dual_agent/cai/hybrid/
  message_features.py
  react_replan.py
  prompts/
    nlp_system.txt
    react_system.txt
    fewshots/
      message_features.json
      react_actions.json
```

---

## 變更紀錄

| 日期 | 說明 |
|------|------|
| 2026-09-01 | 三台分工边界、App 范围条款、System 留 1 样本 + User few-shot 策略 |
