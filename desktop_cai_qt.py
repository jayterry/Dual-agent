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

from PySide6.QtCore import Qt, QThread, Signal, Slot
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
QDialog {
    background: #F9FAFB;
}
"""


class Worker(QThread):
    finished_ok = Signal(str)
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
            face = _build_user_facing_reply(out.answer, out.results)
            result_summary = format_results_for_display(out.results) if out.results else ""
            record_turn(
                self.session,
                user=self.user_text,
                assistant=face,
                task_type=out.task_type,
                task_state=out.task_state,
                model=OLLAMA_MODEL,
                base_url=OLLAMA_BASE_URL,
                plan_summary=build_plan_summary(out.plan),
                result_summary=result_summary,
            )
            self.finished_ok.emit(face)
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

    def append_message(self, role: str, text: str) -> None:
        bubble = ChatBubble(role, text)
        # insert before stretch
        stretch_idx = self.chat_lay.count() - 1
        row = QHBoxLayout()
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble, 0, Qt.AlignRight)
        else:
            row.addWidget(bubble, 0, Qt.AlignLeft)
            row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(row)
        self.chat_lay.insertWidget(stretch_idx, wrap)
        # scroll to bottom
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
        # defer again after layout
        QApplication.processEvents()
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_btn.setEnabled(not busy)
        self.input.setEnabled(not busy)
        self.new_btn.setEnabled(not busy)
        self.status.setText("正在回覆…" if busy else "")

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

    @Slot(str)
    def _on_ok(self, face: str) -> None:
        self.append_message("assistant", face or "已完成。")
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
