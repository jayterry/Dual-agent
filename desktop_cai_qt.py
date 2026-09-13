"""
ScamSentinel 桌面正式介面（PySide6）。

聊天優先；設定放彈窗；不露出內部計畫／技能細節。

  cd Dual-agent
  pip install PySide6
  python desktop_cai_qt.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 重用 Tk 版同一套使用者面向格式／persona 邏輯
from desktop_cai_app import (  # noqa: E402
    _build_user_facing_reply,
    _default_persona,
    _extract_latest_call_dai_payload,
    _persona_dict_from_state,
)

# 中性 Teal，避免紫系／cream terracotta
_STYLESHEET = """
QMainWindow, QWidget#central {
    background: #F3F4F6;
    color: #111827;
    font-family: "Segoe UI", "Microsoft JhengHei UI", sans-serif;
    font-size: 14px;
}
QLabel#brand {
    font-size: 18px;
    font-weight: 700;
    color: #0F766E;
    letter-spacing: 0.5px;
}
QPushButton {
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    padding: 8px 14px;
    color: #111827;
}
QPushButton:hover {
    background: #F9FAFB;
    border-color: #9CA3AF;
}
QPushButton#primary {
    background: #0F766E;
    border: none;
    color: #FFFFFF;
    font-weight: 600;
    min-width: 88px;
}
QPushButton#primary:hover {
    background: #0D9488;
}
QPushButton#primary:disabled {
    background: #99B8B4;
}
QFrame#chatPane {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 14px;
}
QScrollArea#chatScroll {
    background: transparent;
    border: none;
}
QWidget#chatInner {
    background: #FFFFFF;
}
QFrame#bubbleUser {
    background: #DDF3EF;
    border-radius: 14px;
    padding: 2px;
}
QFrame#bubbleAssistant {
    background: #F8FAFC;
    border: 1px solid #E5E7EB;
    border-radius: 14px;
    padding: 2px;
}
QFrame#bubbleHint {
    background: transparent;
    border: none;
}
QLabel#role {
    font-size: 11px;
    font-weight: 600;
    color: #0F766E;
}
QLabel#roleAssistant {
    font-size: 11px;
    font-weight: 600;
    color: #374151;
}
QLabel#roleHint {
    font-size: 11px;
    font-weight: 600;
    color: #6B7280;
}
QLabel#body {
    color: #111827;
    font-size: 14px;
}
QLabel#bodyHint {
    color: #6B7280;
    font-size: 13px;
}
QFrame#composer {
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 14px;
}
QTextEdit#input {
    background: #FFFFFF;
    border: none;
    padding: 10px 12px;
    font-size: 14px;
    color: #111827;
}
QLabel#status {
    color: #B45309;
    font-size: 12px;
    min-height: 16px;
}
QFrame#daiRiskCard {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 16px;
}
QLabel#daiPill {
    background: #FEE2E2;
    color: #B91C1C;
    border-radius: 20px;
    padding: 4px 12px;
    font-weight: 600;
}
QFrame#daiThreatCard {
    background: #1D4ED8;
    border: 1px solid #1E3A8A;
    border-radius: 14px;
}
QFrame#daiThreatCard QLabel {
    color: #FFFFFF;
}
QFrame#daiContextCard {
    background: #0F766E;
    border: 1px solid #115E59;
    border-radius: 14px;
}
QFrame#daiContextCard QLabel {
    color: #FFFFFF;
}
QLabel#daiThreatTitle {
    color: #FFFFFF;
    font-weight: 600;
}
QLabel#daiContextTitle {
    color: #FFFFFF;
    font-weight: 600;
}
QFrame#daiLimitCard {
    background: #B45309;
    border: 1px solid #78350F;
    border-radius: 14px;
}
QFrame#daiLimitCard QLabel {
    color: #FFFFFF;
}
QFrame#pipelineLive {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 12px;
}
QLabel#pipelineLiveTitle {
    font-weight: 700;
    color: #374151;
}
QLabel#pipelineLiveHeadline {
    color: #2563EB;
    font-weight: 600;
}
QLabel#daiLimitLabel {
    color: #FFFFFF;
    font-weight: 700;
}
QDialog {
    background: #F9FAFB;
}
"""


class Worker(QThread):
    finished_ok = Signal(str, object)
    finished_err = Signal(str)

    def __init__(self, user_text: str, persona: dict[str, Any], ctx: Any, session: Any) -> None:
        super().__init__()
        self.user_text = user_text
        self.persona = persona
        self.ctx = ctx
        self.session = session

    def run(self) -> None:  # noqa: D401
        try:
            from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
            from dual_agent.cai.context_layer import (
                build_context_pack_for_turn,
                build_plan_summary,
                record_turn,
            )
            from dual_agent.cai.executor import format_results_for_display
            from dual_agent.cai.plan_execute import run_plan_and_execute

            self.ctx.policy_state["dai_persona"] = dict(self.persona)
            cp = build_context_pack_for_turn(
                self.session,
                self.user_text,
                user_facts=self.ctx.policy_state.get("user_facts"),
                pending_memory_confirm=self.ctx.policy_state.get("pending_memory_confirm"),
            )
            out = run_plan_and_execute(user_text=self.user_text, ctx=self.ctx, context_pack=cp)
            dai = _extract_latest_call_dai_payload(out.results) or {}
            if isinstance(dai.get("path_a"), dict):
                face = (out.answer or "").strip() or "分析完成。"
            else:
                face = _build_user_facing_reply(out.answer, out.results)
            result_summary = format_results_for_display(out.results) if out.results else ""
            stored = face
            display = str(dai.get("display_text") or "").strip()
            if display and display not in stored:
                stored = f"{face}\n\n{display}".strip()
            record_turn(
                self.session,
                user=self.user_text,
                assistant=stored,
                task_type=out.task_type,
                task_state=out.task_state,
                model=OLLAMA_MODEL,
                base_url=OLLAMA_BASE_URL,
                plan_summary=build_plan_summary(out.plan),
                result_summary=result_summary,
            )
            if isinstance(self.ctx.policy_state.get("task_snapshot"), dict):
                # plan_execute 可能已寫 work record；與 session 合併後再回寫 ctx
                merged = dict(self.session.task_snapshot or {})
                merged.update(self.ctx.policy_state["task_snapshot"])
                self.session.task_snapshot = merged
            if dai and isinstance(dai, dict):
                from dual_agent.cai.context_layer import record_turn_after_review

                # 緩衝已由 record_turn 寫入；此處只補審查欄位
                from dual_agent.cai.work_record import on_dai_success

                self.session.task_snapshot = on_dai_success(
                    self.session.task_snapshot,
                    dai=dai,
                    artifact=str((self.ctx.policy_state.get("ingress_payload") or {}).get("artifact_text") or ""),
                )
            self.ctx.policy_state["task_snapshot"] = dict(self.session.task_snapshot or {})
            self.finished_ok.emit(face or "已完成。", dai)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.finished_err.emit(str(e))


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None, persona_state: dict[str, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("個人設定")
        self.setModal(True)
        self.resize(420, 360)
        self._state = persona_state

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        title = QLabel("個人設定")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)
        hint = QLabel("常用 App 代表你平常使用的管道。這則訊息從哪裡來、來訊者關係由系統自動判斷。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6B7280; margin-bottom: 8px;")
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)

        self.age = QComboBox()
        self.age.addItems(["<25", "25-39", "40-59", "60+"])
        self.age.setCurrentText(persona_state.get("age_band", "25-39"))

        self.occ = QComboBox()
        self.occ.addItems(["student", "office", "freelance", "retired", "other"])
        self.occ.setCurrentText(persona_state.get("occupation", "other"))

        self.apps = QLineEdit(persona_state.get("primary_apps", "SMS"))
        self.invest = QLineEdit(persona_state.get("invest_exp", ""))

        form.addRow("年齡", self.age)
        form.addRow("職業", self.occ)
        form.addRow("常用 App", self.apps)
        form.addRow("投資經驗", self.invest)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self) -> None:
        self._state["age_band"] = self.age.currentText()
        self._state["occupation"] = self.occ.currentText()
        self._state["primary_apps"] = self.apps.text().strip() or "SMS"
        self._state["invest_exp"] = self.invest.text().strip()
        self._state.pop("relation_type", None)
        self._state.pop("channel", None)
        try:
            from dual_agent.cai.profile_store import upsert_fields

            upsert_fields(
                {
                    "age_band": self._state["age_band"],
                    "occupation": self._state["occupation"],
                    "primary_apps": self._state["primary_apps"],
                    "invest_exp": self._state["invest_exp"],
                }
            )
        except Exception:  # noqa: BLE001
            pass
        self.accept()


class ChatBubble(QFrame):
    def __init__(self, role: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        kind = "user" if role == "user" else ("hint" if role == "hint" else "assistant")
        self.setObjectName(
            {"user": "bubbleUser", "assistant": "bubbleAssistant", "hint": "bubbleHint"}[kind]
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        role_lbl = QLabel(
            {"user": "你", "assistant": "ScamSentinel", "hint": "提示"}[kind]
        )
        role_lbl.setObjectName(
            {"user": "role", "assistant": "roleAssistant", "hint": "roleHint"}[kind]
        )
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setObjectName("bodyHint" if kind == "hint" else "body")

        lay.addWidget(role_lbl)
        lay.addWidget(body)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        if kind == "user":
            self.setMaximumWidth(520)
        elif kind == "assistant":
            self.setMaximumWidth(640)


def _wrap_label(text: str, object_name: str = "", *, align: Qt.AlignmentFlag = Qt.AlignLeft) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if object_name:
        lbl.setObjectName(object_name)
    lbl.setAlignment(align)
    return lbl


class DaiRiskCard(QFrame):
    def __init__(self, dai: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("daiRiskCard")
        self.setMaximumWidth(720)
        path_a = dai.get("path_a") if isinstance(dai.get("path_a"), dict) else {}
        threat = path_a.get("threat_score_100")
        context = path_a.get("context_score_100")
        clues = list(path_a.get("threat_clues") or dai.get("user_reason_highlights") or [])
        factors = list(path_a.get("context_factors") or [])
        backend = str(path_a.get("context_backend") or "")
        hetero = any(k in backend.lower() for k in ("hetero", "gnn", "sage"))
        ctx_title = "GNN 情境因素" if hetero else "情境因素"
        headline = str(dai.get("headline") or "").strip()
        instruction = str(dai.get("instruction") or "").strip()
        limitations = list(dai.get("limitations") or []) or [
            "本分析由 AI 自動生成，僅供參考，非法律意見或官方判定；分數不代表受害機率。請自行向官方或原服務管道查證後再操作，必要時聯絡 165。"
        ]
        narrator = str(dai.get("narrator_text") or "").strip()
        suggestions = list(dai.get("user_suggestions") or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        if headline:
            pill = _wrap_label(headline, "daiPill")
            pill.setAlignment(Qt.AlignCenter)
            pill.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            root.addWidget(pill, 0, Qt.AlignLeft)
        if instruction:
            root.addWidget(_wrap_label(instruction))

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(
            self._score_box(
                "daiThreatCard",
                "daiThreatTitle",
                "ML / LLM 訊息線索",
                threat,
                " ｜ ".join(str(x) for x in clues) if clues else "—",
            ),
            1,
        )
        ctx_body = "\n".join(str(x) for x in factors) if factors else "—"
        if backend and not hetero:
            ctx_body = f"{ctx_body}\n（{backend}）"
        row.addWidget(
            self._score_box("daiContextCard", "daiContextTitle", ctx_title, context, ctx_body),
            1,
        )
        root.addLayout(row)

        limit = QFrame()
        limit.setObjectName("daiLimitCard")
        lim_lay = QHBoxLayout(limit)
        lim_lay.setContentsMargins(12, 8, 12, 8)
        lim_lay.setSpacing(10)
        lim_lay.addWidget(_wrap_label("限制", "daiLimitLabel"))
        lim_lay.addWidget(_wrap_label(" ".join(str(x) for x in limitations)), 1)
        root.addWidget(limit)

        if narrator:
            root.addWidget(_wrap_label("分析報告"))
            root.addWidget(_wrap_label(narrator))
        for tip in suggestions:
            root.addWidget(_wrap_label(str(tip)))

    @staticmethod
    def _score_box(frame_name: str, title_name: str, title: str, score: Any, body: str) -> QFrame:
        box = QFrame()
        box.setObjectName(frame_name)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        lay.addWidget(_wrap_label(title, title_name, align=Qt.AlignCenter))
        score_txt = f"{int(score)}/100" if isinstance(score, (int, float)) else "—/100"
        score_lbl = _wrap_label(score_txt, align=Qt.AlignCenter)
        score_lbl.setStyleSheet("font-size: 20px; font-weight: 700;")
        lay.addWidget(score_lbl)
        lay.addWidget(_wrap_label(body, align=Qt.AlignCenter))
        return box


class PipelineLivePanel(QFrame):
    """Busy 時兩欄：左時序節點、右思考 log。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pipelineLive")
        self.setMaximumHeight(220)
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(_wrap_label("處理進度", "pipelineLiveTitle"))
        self.headline = _wrap_label("", "pipelineLiveHeadline")
        left.addWidget(self.headline)
        self.flow_scroll = QScrollArea()
        self.flow_scroll.setWidgetResizable(True)
        self.flow_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.flow_body = QLabel("")
        self.flow_body.setWordWrap(True)
        self.flow_body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.flow_scroll.setWidget(self.flow_body)
        left.addWidget(self.flow_scroll, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(_wrap_label("思考過程", "pipelineLiveTitle"))
        self.think_scroll = QScrollArea()
        self.think_scroll.setWidgetResizable(True)
        self.think_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.think_body = QLabel("")
        self.think_body.setWordWrap(True)
        self.think_body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.think_scroll.setWidget(self.think_body)
        right.addWidget(self.think_scroll, 1)

        root.addLayout(left, 1)
        root.addLayout(right, 1)

    def update_status(self, status: dict[str, Any]) -> None:
        headline = str(status.get("headline_zh") or status.get("label_zh") or "處理中…")
        self.headline.setText(headline)
        nodes = status.get("nodes") or []
        flow_lines: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            st = str(node.get("status") or "pending")
            mark = "●" if st == "active" else ("✓" if st == "done" else "○")
            label = str(node.get("label_zh") or node.get("id") or "")
            flow_lines.append(f"{mark} {label}")
        self.flow_body.setText("\n".join(flow_lines) if flow_lines else "準備中…")

        thinking = status.get("thinking") if isinstance(status.get("thinking"), dict) else {}
        entries = thinking.get("entries") or []
        think_lines: list[str] = []
        for row in entries:
            if not isinstance(row, dict):
                continue
            if str(row.get("kind") or "") == "finish":
                continue
            label = str(row.get("label_zh") or "").strip()
            detail = row.get("detail")
            text = ""
            if isinstance(detail, dict):
                text = str(detail.get("text") or detail.get("thought") or "").strip()
            elif isinstance(detail, str):
                text = detail.strip()
            if label:
                think_lines.append(f"• {label}")
            if text:
                think_lines.append(f"  {text}")
        self.think_body.setText("\n".join(think_lines) if think_lines else "開始處理…")
        bar = self.think_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ScamSentinel")
        self.resize(900, 720)
        self.setMinimumSize(720, 560)

        from dual_agent.cai.context_layer import SessionMemory
        from dual_agent.skill_types import SkillContext

        self.persona_state = _default_persona()
        self.ctx = SkillContext(user_input="")
        self.session = SessionMemory()
        self._worker: Worker | None = None
        self._busy = False

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # top bar
        top = QHBoxLayout()
        brand = QLabel("ScamSentinel")
        brand.setObjectName("brand")
        top.addWidget(brand)
        top.addStretch(1)
        self.new_btn = QPushButton("新對話")
        self.settings_btn = QPushButton("設定")
        top.addWidget(self.new_btn)
        top.addWidget(self.settings_btn)
        root.addLayout(top)

        self.status = QLabel("")
        self.status.setObjectName("status")
        root.addWidget(self.status)

        self.pipeline_panel = PipelineLivePanel()
        self.pipeline_panel.hide()
        root.addWidget(self.pipeline_panel)
        self._pipe_timer = QTimer(self)
        self._pipe_timer.setInterval(400)
        self._pipe_timer.timeout.connect(self._poll_pipeline)

        # chat pane
        pane = QFrame()
        pane.setObjectName("chatPane")
        pane_lay = QVBoxLayout(pane)
        pane_lay.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("chatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.chat_inner = QWidget()
        self.chat_inner.setObjectName("chatInner")
        self.chat_lay = QVBoxLayout(self.chat_inner)
        self.chat_lay.setContentsMargins(16, 16, 16, 16)
        self.chat_lay.setSpacing(12)
        self.chat_lay.addStretch(1)
        self.scroll.setWidget(self.chat_inner)
        pane_lay.addWidget(self.scroll)
        root.addWidget(pane, stretch=1)

        # composer
        composer = QFrame()
        composer.setObjectName("composer")
        composer.setMinimumHeight(120)
        c_lay = QHBoxLayout(composer)
        c_lay.setContentsMargins(8, 8, 8, 8)
        c_lay.setSpacing(8)

        self.input = QTextEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText("輸入訊息或貼上簡訊…")
        self.input.setAcceptRichText(False)
        self.input.setMinimumHeight(88)
        self.input.setMaximumHeight(140)

        self.send_btn = QPushButton("送出")
        self.send_btn.setObjectName("primary")
        self.send_btn.setCursor(Qt.PointingHandCursor)

        c_lay.addWidget(self.input, stretch=1)
        c_lay.addWidget(self.send_btn, alignment=Qt.AlignBottom)
        root.addWidget(composer)

        self.new_btn.clicked.connect(self.on_new_chat)
        self.settings_btn.clicked.connect(self.on_settings)
        self.send_btn.clicked.connect(self.on_send)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.on_send)

        self.append_message(
            "hint",
            "你好，我是 ScamSentinel。\n貼上可疑簡訊，或直接問我問題。\n右上角「設定」可調整個人情境（可選）。",
        )
        self.input.setFocus()

    def append_message(self, role: str, text: str, dai: dict[str, Any] | None = None) -> None:
        stretch_idx = self.chat_lay.count() - 1
        col = QVBoxLayout()
        col.setSpacing(8)
        if (text or "").strip():
            col.addWidget(ChatBubble(role, text))
        if role != "user" and isinstance(dai, dict) and isinstance(dai.get("path_a"), dict):
            col.addWidget(DaiRiskCard(dai))
        row = QHBoxLayout()
        if role == "user":
            row.addStretch(1)
            row.addLayout(col)
        else:
            row.addLayout(col)
            row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(row)
        self.chat_lay.insertWidget(stretch_idx, wrap)
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
        QApplication.processEvents()
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_btn.setEnabled(not busy)
        self.input.setEnabled(not busy)
        self.new_btn.setEnabled(not busy)
        self.status.setText("正在回覆…" if busy else "")
        if busy:
            self.pipeline_panel.show()
            self._poll_pipeline()
            self._pipe_timer.start()
        else:
            self._pipe_timer.stop()
            self.pipeline_panel.hide()

    def _poll_pipeline(self) -> None:
        from dual_agent.cai.pipeline_progress import get_pipeline_status

        try:
            status = get_pipeline_status(self.ctx)
        except Exception:  # noqa: BLE001
            return
        self.pipeline_panel.update_status(status)

    @Slot()
    def on_settings(self) -> None:
        dlg = SettingsDialog(self, self.persona_state)
        dlg.exec()

    @Slot()
    def on_new_chat(self) -> None:
        if self._busy:
            return
        from dual_agent.cai.context_layer import SessionMemory
        from dual_agent.skill_types import SkillContext

        self.ctx = SkillContext(user_input="")
        self.session = SessionMemory()
        # clear bubbles
        while self.chat_lay.count() > 1:
            item = self.chat_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.append_message("hint", "已開始新對話。直接輸入或貼上簡訊即可。")
        self.input.clear()
        self.input.setFocus()

    @Slot()
    def on_send(self) -> None:
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.append_message("user", text)
        self.set_busy(True)
        persona = _persona_dict_from_state(self.persona_state)
        self._worker = Worker(text, persona, self.ctx, self.session)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.start()

    @Slot(str, object)
    def _on_ok(self, face: str, dai: object) -> None:
        payload = dai if isinstance(dai, dict) else None
        self.append_message("assistant", face or "", payload)
        self.set_busy(False)
        self.input.setFocus()

    @Slot(str)
    def _on_err(self, _msg: str) -> None:
        self.append_message("assistant", "抱歉，處理時發生問題，請稍後再試。")
        self.set_busy(False)
        self.input.setFocus()

    def closeEvent(self, event) -> None:  # noqa: N802
        w = self._worker
        if w is not None and w.isRunning():
            w.wait(120_000)
        super().closeEvent(event)


def main() -> None:
    # 必須在 QApplication 建立前設定
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(_STYLESHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
