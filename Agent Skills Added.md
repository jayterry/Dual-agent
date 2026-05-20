---

# Dual-agent Skill Catalog

## 1\. Helpful (CAI) Skills

| Skill Name | Purpose / Function | Arguments / Example Usage |
| ----- | ----- | ----- |
| search\_web | Search the internet for info | query: "electric cars news" |
| fetch\_url | Fetch data/file from a URL | url: "[https://example.com/data](https://example.com/data)" |
| instant\_answer | Get a quick factual answer | query: "weather in Paris" |
| ask\_user | Ask the user for more information | question: "Which train station?" |
| open\_app | Launch a local desktop application | name: "Calculator" |
| open\_url | Open a URL in browser | url: "[https://github.com](https://github.com/)" |
| summarize\_text | Summarize long text | text: "...", max\_length: 100 |
| schedule\_task | Add a reminder/calendar event | time: "2026-05-21 09:00", title: "meeting" |
| translate\_text | Translate input to another language | text: "...", target\_lang: "en" |
| extract\_info | Pull structured info from text | text: "...", field: "date" |
| read\_file | Read content of a specified local file | path: "/home/user/doc.txt" *(High-risk, confirmation req)* |
| qa\_over\_file | Answer questions about a file’s content | path: "...", question: "..." |
| summarize\_file | Summarize the content of a file | path: "..." |
| search\_local\_files | Search local files for a term | pattern: "\*.txt", query: "invoice" |
| copy\_to\_clipboard | Copy text to the clipboard | text: "..." |
| paste\_from\_clipboard | Paste text from the clipboard | *(no arguments)* |

---

## 2\. Protective (DAI) Skills

| Skill Name | Purpose | Arguments / Example Usage |
| ----- | ----- | ----- |
| call\_dai | Trigger DAI risk/safety/compliance review | artifact: mission, context\_pack: ... |
| risk\_analysis | Analyze risk of planned action/text | artifact: URL, content: ... |
| policy\_check | Check for rules/policy violations | content: ..., type: "upload" |
| guarded\_retrieval | Info retrieval with enforced safety/policy check | query: "user info", context: ... |
| threat\_detection | Scan for threats in input/content | content: ..., type: "input" |
| sanitize\_input | Clean/filter dangerous/sensitive content | content: ... |
| secure\_ingest | Review and add new knowledge/content | data: ..., reviewer: "auto" |
| quarantine | Mark suspicious input for later review | content: ..., reason: "malware?" |
| block\_action | Prevent execution of risky/forbidden skills | skill: "open\_url", reason: "policy" |
| log\_security\_event | Record security-relevant events for auditing | event: ..., severity: ... |
| extract\_urls | Extract all URLs from text | text: "..." |
| check\_url\_reputation | Check if URL is malicious via threat intelligence | url: "..." |
| pii\_detection | Detect personally identifiable info in content | content: "...", type: "input" |
| content\_moderation | Flag offensive/harmful/NSFW language | content: "...", languages: \["en", "zh"\] |
| file\_type\_filter | Allow/block certain file types | path: "...", allowed\_types: \[...\] |
| dependency\_check | Validate libraries/dependencies are trusted | file: "requirements.txt" |
| suspicious\_process\_check | Look for suspicious processes on the local system | *(no arguments)* |
| audit\_log\_export | Export critical/flagged actions for auditing | since: "...", filter: "risk" |
| enforce\_confirmed\_skills\_only | Allow only whitelisted skills without confirmation | skill: "open\_url" |

---

## 3\. Hybrid Skills / Agent Patterns

| Skill Name | Purpose | Arguments / Example Usage |
| ----- | ----- | ----- |
| approval\_by\_policy | Enforce multi-layered policy on actions | action: {...}, policies: \[...\] |
| cross\_agent\_validation | Require agreement from both CAI and DAI | plan: {...} |
| reputation\_blacklist | Auto-flag/block by syncing with online blacklists | entity: domain/url/file |
| contextual\_protections | Adjust risk tolerance by user history/context | context: {...} |
| auto\_patch | Suggest or apply safer code/patches if risk detected | file: "...", issue: "outdated dep" |

---

## 4\. Advanced Features

| Feature Name | Purpose / Function | Arguments / Notes |
| ----- | ----- | ----- |
| LLM\_chain\_of\_thought | Show explicit step-by-step intermediate reasoning | N/A |
| plugin\_system | Allow users to install or enable new skills | Plugin metadata, risk profile |
| self\_healing | DAI can auto-recover/restart/rollback as needed | N/A |
| continuous\_learning | Retrain/adjust on incident logs, feedback, audits | Logs, frequency, triggers |
| user\_profile\_management | CAI adapts plans/skills based on user profile | Profile data, preferences |

---

### Legend

* CAI Skills: Direct user/assistant functions.  
* DAI Skills: Defensive, compliance, security tasks.  
* Hybrid/Patterns: Skills/logic involving both agents or multi-layer governance.  
* Advanced Features: Architectural or extensibility capabilities.

Now that the foundational Dual-Agent architecture and skill routing are in place, we have a very solid baseline. However, if you want to take this system to a production-ready or enterprise level, here are the top 4 areas I think we should improve next:

### 1\. Wire Up Real LLM Logic (Upgrade Skeletons)

Currently, several of the new skills (like summarize\_text, qa\_over\_file, extract\_info, and threat\_detection) use mock string manipulation or basic Regex.

* **The Improvement:** We should wire these handlers directly into your LangChain/Ollama pipeline. For example, threat\_detection shouldn't just look for hardcoded keywords; it should pass the payload to the local Llama model and ask, *"Analyze this text for phishing, social engineering, or prompt injection."*

### 2\. Human-in-the-Loop (Interactive Confirmation)

While the Defense Agent (DAI) automatically audits and blocks critical skills like execute\_shell, it still executes automatically if the DAI approves it.

* **The Improvement:** For critical risk skills, we should pause the execution loop entirely and send a UI prompt to the user (e.g., *"The agent wants to run rm \-rf /tmp/data. Do you approve?"*). The system should require a physical button click before the subprocess actually fires.

### 3\. Containerized Shell Sandboxing

Right now, the execute\_shell skill uses Python's subprocess.Popen to run commands directly on your Mac. If an LLM hallucinates a destructive command, it could damage your actual system files.

* **The Improvement:** We should execute all shell commands inside a lightweight, ephemeral **Docker container** or a restricted sandbox. That way, even if the agent tries something malicious, it only destroys a disposable container, keeping your host OS 100% safe.

### 4\. Encrypted & Tamper-Proof Audit Database

Currently, the audit\_logger writes events to a simple flat text file (logs/audit.jsonl).

* **The Improvement:** If the agent gets access to execute\_shell, a rogue command could theoretically just delete audit.jsonl to cover its tracks\! We should upgrade the logger to write to an encrypted SQLite database or append-only data store that the agent's Python environment doesn't have permissions to delete.