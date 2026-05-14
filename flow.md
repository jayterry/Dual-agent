# Dual-Agent 流程圖（Mermaid 合併版）

本文件將視覺稿中的多張流程圖合併為可版本控制的 **Mermaid** 描述，並與 `projrct.md` 的架構邊界對齊。實作時以型別與模組邊界為準；圖表為行為摘要。

---

## 圖例與對齊說明（正式規格語意）

- **Planner / Replan**：可為不同提示詞的同一角色（兩段 LLM），圖中分開標示。
- **DAI 觸發點（唯一）**：凡需要走 DAI，**下一個可執行的 Todo\[0\] 型別即為 `call_dai`**。Executor **不**另做「要不要叫 DAI」的平行判定；是否需 DAI 已反映在佇列裡。
- **非 `call_dai` 的 Todo\[0]**：一律走 **一般 Executor → Observation（執行結果／觀察）→ Replan**。
- **DAI Memory 讀寫**：在 **風險分析**、**Guarded Retrieval** 等 `call_dai` 管線內，對 DAI Memory（含 Safe / Threat / Policy / Quarantine 等）**僅能讀取**，**不**因單次分析／檢索而寫入。
- **寫入 DAI Memory 的唯一管道**：**Secure Ingestion**（正規化 → 消毒／結構化 → Ingestion Review → Store／Quarantine／Reject 後之持久化）。
- **CAI 不得直接存取 DAI 所屬 DB**：僅能透過 **`call_dai`**（與入庫 API，若由受控服務暴露）取得 `DAIResult`／安全上下文；不得繞過 DAI 直寫記憶庫。

---

## 1. Memory／Context Layer（10 輪＋滾動摘要）

```mermaid
flowchart TD
  UP([User Prompt])
  LM[[Load Memory]]

  subgraph MEM[Memory / Context Layer]
    RCB[Recent Context Buffer<br/>最近約 10 輪互動]
    RS[Rolling Summary<br/>長期摘要]
    TS[Task State<br/>目前任務狀態]
  end

  UP --> MEM
  LM -.-> MEM

  MEM --> CP[Context Packer]
  CP --> PACK[Context Pack]
  PACK --> PR[Plan / Replan]

  PR --> OUT[Result / Observation / Answer]

  OUT --> UTS[更新 Task State]
  OUT --> URC[更新 Recent Context Buffer]

  UTS --> Q10{超過 10 輪?}
  URC --> Q10

  Q10 -->|否 ≤10 輪| UP
  Q10 -->|是 >10 輪| COMP[Compress to Rolling Summary]
  COMP -.-> LM
```

---

## 2. CAI 主迴路：Planner → Executor ⇄ Replan（含一般問答捷徑）

```mermaid
flowchart TD
  UPC([User Prompt + Context Pack])

  UPC --> PL[Planner LLM<br/>任務型態 / 延續性 / TaskState / 初始 Todo]

  PL --> EMP{Todo 為空?}

  EMP -->|是 · 一般問答| RP[Replan LLM<br/>直接產生回答或追問]
  EMP -->|否 · 需執行| RUN[TaskState: running 等]
  RUN --> EX[Executor<br/>僅執行 Todo0]

  EX --> KIND{Todo0 == call_dai ?}

  KIND -->|否| RES[Observation<br/>一般工具／技能結果]
  KIND -->|是| DAIQ[call_dai 管線<br/>唯讀 DAI Memory → DAIResult]
  DAIQ --> RES

  RES --> RP

  RP --> TC{任務完成?}

  TC -->|否| EX
  TC -->|是| FA([Final Answer])

  RP -->|資訊不足 · ask_user| WAIT[waiting_input / pending_task]
  WAIT --> UPC
```

---

## 3. DAI 管線（僅當 Todo0 = call_dai 由 Executor 進入）

**Planner／Replan** 負責把「需要 DAI」排成 **`call_dai`** 這個 Todo；本圖從 **call_dai 輸入** 開始，不另畫「要不要 DAI」菱形。此管線對 DAI Memory **只讀**；持久化寫入僅見 **§4 Secure Ingestion**。

```mermaid
flowchart TD
  IN_DAI[call_dai 輸入<br/>Context Pack + User Prompt + CAI Todo]

  IN_DAI --> D_LLM[DAI Defense LLM<br/>防禦性分析]

  D_LLM --> DTYPE{Defense Task Type}

  DTYPE -->|Risk Analysis| DTODO[產生 Defense Todo]
  DTYPE -->|Guarded Retrieval| DTODO
  DTYPE -->|Both| DTODO

  DTODO --> D_EX[DAI Executor<br/>防禦子任務 · 讀取 Memory]

  D_EX --> DRES[DAI Result<br/>Safety Report · Evidence · Risk Score<br/>Tool Restrictions · Safe Context]

  DRES --> CAI_RP[CAI Replan<br/>Observation 承載 DAIResult]

  CAI_RP --> DEC{依 DAI Result 決定}

  DEC -->|New Todo| PLN[CAI Planner／Replan<br/>下一個 Todo0 可為 call_dai 或一般]
  DEC -->|Modify Todo| PLN
  DEC -->|Block Tool| PLN
  DEC -->|Need User Input| PLN
  DEC -->|Final Answer| END_U([回答使用者])
```

---

## 4. 完整端到端：圖 1 + 圖 2 + DAI Memory（讀／寫分離）+ Secure Ingestion

- **call_dai 路徑**：Executor 僅在 **Todo0 = call_dai** 時進入；對 **DAI Memory 僅讀**。
- **Secure Ingestion**：**唯一**對 DAI Memory 做**持久化寫入**的路徑（圖中以 **寫入** 標示）。

```mermaid
flowchart TD
  subgraph ENTRY[輸入與上下文]
    U([User Prompt])
    LM[[Load Memory]]
    subgraph MEM2[Memory / Context Layer]
      RCB2[Recent 10 輪]
      RS2[Rolling Summary]
      TS2[Task State]
    end
    U --> MEM2
    LM -.-> MEM2
    MEM2 --> CP2[Context Packer]
    CP2 --> PACK2[Context Pack]
  end

  PACK2 --> PL2[Planner LLM]

  PL2 --> E2{Todo 為空?}
  E2 -->|是| RP2[Replan LLM]
  E2 -->|否| EX2[Executor · Todo0]

  EX2 --> T0{Todo0 == call_dai ?}
  T0 -->|否| OBS[Observation<br/>一般執行結果]
  T0 -->|是| CD[call_dai → DAI Defense Agent]

  subgraph DAI[DAI 子系統 · call_dai 不寫入 Memory]
    CD --> DDL[Defense LLM / Task Type / Defense Todo]
    DDL --> DEX2[DAI Executor]
    subgraph DAIMEM[DAI Memory Layer]
      SK[(Safe Knowledge)]
      TH[(Threat Memory)]
      POL[(Policy / Rule)]
      QU[(Quarantine)]
    end
    DEX2 -.->|僅讀取| SK
    DEX2 -.->|僅讀取| TH
    DEX2 -.->|僅讀取| POL
    DEX2 -.->|僅讀取| QU
    DEX2 --> DR2[DAI Result → Observation]
  end

  subgraph ING[Secure Ingestion · 唯一寫入 DAI Memory]
    RAW[Candidate / Raw Data] --> NSS[Normalize · Sanitize · Structure]
    NSS --> IR[Ingestion Review]
    IR --> SD{Store / Quarantine / Reject}
    SD -->|寫入| SK
    SD -->|寫入| TH
    SD -->|寫入| QU
  end

  OBS --> RP2
  DR2 --> RP2

  RP2 --> TC2{任務完成?}
  TC2 -->|否| EX2
  TC2 -->|是| FA2([Final Answer])

  FA2 --> UTS2[更新 Task State / Recent]
  UTS2 --> U
```

---

## 5. 單回合互動（Sequence，摘要）

```mermaid
sequenceDiagram
  autonumber
  participant User
  participant Mem as Memory Layer
  participant Pack as Context Packer
  participant Pl as Planner LLM
  participant Ex as Executor
  participant DAI as DAI call_dai
  participant Rp as Replan LLM

  User->>Mem: prompt
  Mem->>Pack: load + pack
  Pack->>Pl: context pack
  Pl->>Ex: Todo0（一般技能或 call_dai）
  alt Todo0 == call_dai
    Ex->>DAI: call_dai（讀 DAI Memory）
    DAI-->>Ex: DAIResult
    Ex-->>Rp: Observation 承載 DAIResult
  else 一般 Todo0
    Ex-->>Rp: Observation
  end
  Rp->>User: final answer 或 追問 / 下一輪 Todo
  Rp->>Mem: persist state + buffer
```

---

## 6. 與 `projrct.md` 的對照檢查清單

| 項目 | 圖中節點 |
|------|-----------|
| DAI 觸發 | **Todo0 = call_dai**；無 Executor 外重複判定 |
| 非 DAI Todo | 圖 2：`Todo0 != call_dai` → Observation → Replan |
| CAI 不直連 DB | CAI 經 `call_dai`／入庫管線；不直寫 DAI Memory |
| `call_dai` 與 Memory | 圖 4：虛線 **僅讀取** DAI Memory |
| 寫入 Memory | 僅 **Secure Ingestion**（圖 4 實線 **寫入**） |
| Max Replan 迭代 | 圖中未畫計數器；實作須外加上限（見規格） |
| `waiting_input` | 圖 2 `ask_user` 迴圈 |
| Policy／Rule 不依賴純向量 | 圖 4 `Policy / Rule` 與向量庫分離；`call_dai` 可讀取 |

---

## 在本地預覽 Mermaid

- VS Code／Cursor：安裝 **Mermaid** 預覽擴充功能後開啟本檔預覽。
- 或將各段程式碼貼至 [Mermaid Live Editor](https://mermaid.live) 檢查語法。

若你之後調整節點命名或 **Ingestion** 路由（例如 Policy 是否由入庫寫入），建議只改本檔與 `projrct.md` 其中一處為「規格真實來源」，另一處用連結引用，避免雙份漂移。
