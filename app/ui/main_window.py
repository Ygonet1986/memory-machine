"""Main chat window."""

from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import topics as topics_mod
from ..backend import Backend
from .graph_dialog import GraphDialog
from .settings_dialog import SettingsDialog
from .tape_dialog import TapeDialog


class ChatWorker(QThread):
    ok = Signal(dict)
    err = Signal(str)
    token = Signal(str, str)

    def __init__(self, backend: Backend, task: str, use_web: bool, parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._task = task
        self._use_web = use_web

    def run(self) -> None:  # noqa: D102 (Qt override)
        try:
            result = self._backend.run(
                self._task,
                use_web=self._use_web,
                on_token=lambda c, r: self.token.emit(c, r),
            )
            self.ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.err.emit(str(e))


class InputBox(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


def _scrollable(widget: QWidget, max_height: int) -> QScrollArea:
    """Wrap a widget in a scroll area bounded by ``max_height``."""
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setMaximumHeight(max_height)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    return area


class MainWindow(QMainWindow):
    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self._backend = backend
        self._worker: ChatWorker | None = None
        self._stream_reasoning = ""
        self._stream_content = ""
        self.setWindowTitle("Memory Machine")
        self.resize(760, 640)
        self._build_ui()
        QShortcut(QKeySequence("Ctrl+Shift+C"), self,
                  activated=self._open_companion)
        self._refresh_topics()
        self._refresh_status()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_scroll = _scrollable(self.status_label, 48)
        root.addWidget(self.status_scroll)

        self.whiteboard_label = QLabel()
        self.whiteboard_label.setWordWrap(True)
        self.whiteboard_label.setTextFormat(Qt.TextFormat.RichText)
        self.whiteboard_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.whiteboard_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.whiteboard_label.setStyleSheet(
            "QLabel { background: #161d27; color: #b8c4d4; border: 1px solid #2c3847; "
            "border-radius: 6px; padding: 8px; font-size: 12px; }"
        )
        self.whiteboard_scroll = _scrollable(self.whiteboard_label, 160)
        root.addWidget(self.whiteboard_scroll)

        topic_row = QHBoxLayout()
        topic_row.addWidget(QLabel("Topic:"))
        self.topic_combo = QComboBox()
        self.topic_combo.activated.connect(self._on_topic_changed)
        topic_row.addWidget(self.topic_combo, 1)
        self.auto_check = QCheckBox("Auto topic")
        self.auto_check.setToolTip("Infer the topic from each message and switch tapes automatically")
        self.auto_check.toggled.connect(self._on_auto_toggled)
        topic_row.addWidget(self.auto_check)
        self.new_topic_btn = QPushButton("New topic")
        self.new_topic_btn.clicked.connect(self._new_topic)
        self.rename_btn = QPushButton("Label")
        self.rename_btn.clicked.connect(self._rename_topic)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_topic)
        topic_row.addWidget(self.new_topic_btn)
        topic_row.addWidget(self.rename_btn)
        topic_row.addWidget(self.delete_btn)
        root.addLayout(topic_row)

        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        self.chat.setStyleSheet(
            "QTextBrowser { background: #14181f; color: #e8eef7; border: none; "
            "padding: 12px; font-size: 14px; }"
        )
        root.addWidget(self.chat, 1)

        self.reasoning_label = QLabel()
        self.reasoning_label.setWordWrap(True)
        self.reasoning_label.setTextFormat(Qt.TextFormat.RichText)
        self.reasoning_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.reasoning_label.setStyleSheet(
            "QLabel { background: #161d27; color: #9fb2c8; border: 1px solid #2c3847; "
            "border-radius: 6px; padding: 8px; font-size: 12px; }"
        )
        self.reasoning_scroll = _scrollable(self.reasoning_label, 140)
        self.reasoning_scroll.hide()
        root.addWidget(self.reasoning_scroll)

        self.answer_label = QLabel()
        self.answer_label.setWordWrap(True)
        self.answer_label.setTextFormat(Qt.TextFormat.RichText)
        self.answer_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.answer_label.setStyleSheet(
            "QLabel { background: #161d27; color: #e8eef7; border: 1px solid #2c3847; "
            "border-radius: 6px; padding: 8px; font-size: 13px; }"
        )
        self.answer_scroll = _scrollable(self.answer_label, 200)
        self.answer_scroll.hide()
        root.addWidget(self.answer_scroll)

        self.input = InputBox()
        self.input.setPlaceholderText("Ask about your project… (Enter to send, Shift+Enter for newline)")
        self.input.setMaximumHeight(120)
        self.input.setStyleSheet(
            "QPlainTextEdit { background: #1e2630; color: #e8eef7; border: 1px solid #2c3847; "
            "border-radius: 6px; padding: 8px; font-size: 14px; }"
        )
        self.input.submitted.connect(self._send)
        root.addWidget(self.input)

        row = QHBoxLayout()
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self._open_settings)
        self.add_files_btn = QPushButton("Add files")
        self.add_files_btn.clicked.connect(self._add_files)
        self.clear_docs_btn = QPushButton("Clear docs")
        self.clear_docs_btn.setToolTip(
            "Delete all attached documents (reference store and tape chunks)"
        )
        self.clear_docs_btn.clicked.connect(self._clear_docs)
        self.memory_btn = QPushButton("Memory")
        self.memory_btn.clicked.connect(self._open_tape)
        self.graph_btn = QPushButton("Graph")
        self.graph_btn.setToolTip("Graph Memory viewer: entities, paths, provenance and review")
        self.graph_btn.clicked.connect(self._open_graph)
        self.companion_btn = QPushButton("Companion")
        self.companion_btn.setToolTip(
            "Open the Companion window (fictional character with relationship memory)"
        )
        self.companion_btn.clicked.connect(self._open_companion)
        self.web_check = QCheckBox("Web search")
        self.web_check.setToolTip("Search the web for this message (does not touch memory)")
        row.addWidget(self.settings_btn)
        row.addWidget(self.add_files_btn)
        row.addWidget(self.clear_docs_btn)
        row.addWidget(self.memory_btn)
        row.addWidget(self.graph_btn)
        row.addWidget(self.companion_btn)
        row.addWidget(self.web_check)
        row.addStretch(1)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn)
        root.addLayout(row)

        self.setCentralWidget(central)
        self._append_system(
            "Welcome to Memory Machine. Each topic has its own tape, and memory "
            "agents are created as that tape grows."
        )

    # ------------------------------------------------------------- topics

    def _refresh_topics(self) -> None:
        current = self._backend.current_topic().get("id", "")
        auto = self._backend.multi_topic()
        self.auto_check.blockSignals(True)
        self.auto_check.setChecked(auto)
        self.auto_check.blockSignals(False)
        self.topic_combo.blockSignals(True)
        self.topic_combo.clear()
        for t in self._backend.list_topics():
            self.topic_combo.addItem(topics_mod.display_name(t), t["id"])
            if t["id"] == current:
                self.topic_combo.setCurrentIndex(self.topic_combo.count() - 1)
        self.topic_combo.blockSignals(False)
        self.topic_combo.setEnabled(not auto)

    def _on_auto_toggled(self, checked: bool) -> None:
        self._backend.set_multi_topic(checked)
        self.topic_combo.setEnabled(not checked)
        if checked:
            self._append_system("Auto topic on: the app will infer the topic from each message.")
        else:
            self._append_system("Auto topic off: manual topic selection.")
        self._refresh_status()

    def _on_topic_changed(self, index: int) -> None:
        topic_id = self.topic_combo.itemData(index)
        if topic_id == self._backend.current_topic().get("id"):
            return
        if self._backend.switch_topic(topic_id):
            self.chat.clear()
            self._append_system(f"Switched to topic: {self._backend.current_topic().get('name')}")
            self._refresh_status()

    def _new_topic(self) -> None:
        topic = self._backend.new_topic()
        self.chat.clear()
        self._append_system(f"Started new topic: {topics_mod.display_name(topic)} (new tape)")
        self._refresh_topics()
        self._refresh_status()

    def _rename_topic(self) -> None:
        current = self._backend.current_topic()
        label, ok = QInputDialog.getText(
            self, "Label topic", "Optional label (blank = use date/time):",
            text=current.get("label", ""),
        )
        if not ok:
            return
        if self._backend.set_label(current["id"], label.strip()):
            self._refresh_topics()
            self._refresh_status()
            self._append_system(f"Label set: {topics_mod.display_name(self._backend.current_topic())}")

    def _delete_topic(self) -> None:
        current = self._backend.current_topic()
        reply = QMessageBox.question(
            self,
            "Delete topic",
            f'Delete topic "{current.get("name")}" and its whole tape? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = self._backend.delete_topic(current["id"])
        if result.get("ok"):
            self.chat.clear()
            self._append_system(f'Deleted topic: {result["removed"]["name"]}')
            self._refresh_topics()
            self._refresh_status()

    # ------------------------------------------------------------- actions

    def _send(self) -> None:
        if self._worker is not None:
            return
        task = self.input.toPlainText().strip()
        if not task:
            return
        if not self._backend.configured():
            self._append_system("Set your DeepSeek API key in Settings first.")
            self._open_settings()
            return
        self.input.clear()
        self._append_user(task)
        self._stream_reasoning = ""
        self._stream_content = ""
        self.reasoning_label.setText("")
        self.answer_label.setText("")
        self.reasoning_scroll.show()
        self.answer_scroll.show()
        self._set_busy(True)
        self._worker = ChatWorker(self._backend, task, self.web_check.isChecked(), parent=self)
        self._worker.ok.connect(self._on_ok)
        self._worker.err.connect(self._on_err)
        self._worker.token.connect(self._on_token)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_token(self, content: str, reasoning: str) -> None:
        self._stream_reasoning += reasoning
        self._stream_content += content
        if self._stream_reasoning:
            r = html.escape(self._stream_reasoning).replace("\n", "<br>")
            self.reasoning_label.setText(f'<b style="color:#5db9ff">Reasoning</b><br>{r}')
            bar = self.reasoning_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        if self._stream_content:
            c = html.escape(self._stream_content).replace("\n", "<br>")
            self.answer_label.setText(f'<b style="color:#9fd79f">Answer</b><br>{c}')
            bar = self.answer_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_ok(self, result: dict[str, Any]) -> None:
        self.reasoning_scroll.hide()
        self.answer_scroll.hide()
        reply = result.get("reply", "")
        annotations = result.get("kept_annotations") or []
        saved = result.get("memories_saved") or []
        reasoning = result.get("reasoning") or ""
        self._append_assistant(reply, annotations, saved, reasoning)
        self._refresh_status()

    def _on_err(self, message: str) -> None:
        self.reasoning_scroll.hide()
        self.answer_scroll.hide()
        self._append_system(f"Error: {message}")

    def _on_done(self) -> None:
        self._worker = None
        self._set_busy(False)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec():
            self._backend.reload()
            self._refresh_topics()
            self._refresh_status()
            self._append_system("Settings saved.")

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add .txt files (RAG + tape)", "", "Text files (*.txt)"
        )
        added = 0
        chunks = 0
        for p in paths:
            res = self._backend.add_document(p)
            if res.get("ok"):
                added += 1
                chunks += (res.get("attached") or {}).get("saved", 0)
        if added:
            msg = f"Added {added} document(s) as reference (RAG)"
            if chunks:
                msg += f" and {chunks} chunk(s) to the tape"
            self._append_system(msg + ".")
        self._refresh_status()

    def _clear_docs(self) -> None:
        docs = self._backend.list_documents()
        chunks = sum(
            1 for m in self._backend.list_memories() if m.get("type") == "attachment"
        )
        if not docs and not chunks:
            self._append_system("No attached documents to delete.")
            return
        answer = QMessageBox.question(
            self,
            "Delete attached documents",
            f"Delete {len(docs)} document(s) and {chunks} memory chunk(s)?\n"
            "Regular memories are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        res = self._backend.remove_all_documents()
        self._append_system(
            f"Deleted {res.get('documents', 0)} document(s) and "
            f"{res.get('chunks', 0)} memory chunk(s)."
        )
        self._refresh_status()

    def _open_tape(self) -> None:
        TapeDialog(self._backend, self).exec()
        self._refresh_status()

    def _open_companion(self) -> None:
        from ..companion_launcher import open_companion

        open_companion()

    def _open_graph(self) -> None:
        GraphDialog(self._backend, self).exec()
        self._refresh_status()

    def _set_busy(self, busy: bool) -> None:
        self.send_btn.setEnabled(not busy)
        self.new_topic_btn.setEnabled(not busy)
        self.rename_btn.setEnabled(not busy)
        self.delete_btn.setEnabled(not busy)
        self.auto_check.setEnabled(not busy)
        self.topic_combo.setEnabled(not busy and not self._backend.multi_topic())
        self.settings_btn.setEnabled(not busy)
        self.add_files_btn.setEnabled(not busy)
        self.clear_docs_btn.setEnabled(not busy)
        self.graph_btn.setEnabled(not busy)
        self.web_check.setEnabled(not busy)
        self.input.setEnabled(not busy)
        if busy:
            self.status_label.setText("Thinking…")

    def _refresh_status(self) -> None:
        try:
            st = self._backend.status()
        except Exception:  # noqa: BLE001
            return
        subject = st.get("whiteboard_subject") or "(no subject)"
        auto = "Auto → " if st.get("multi_topic") else ""
        docs = st.get("documents") or 0
        self.status_label.setText(
            f"{auto}{st.get('topic_name')}   ·   Subject: {subject}   ·   "
            f"Tape: {st.get('tape_records')} memories   ·   {st.get('agents')} agents   "
            f"·   {docs} docs"
        )
        meta = st.get("whiteboard_metacognition") or ""
        checklist = st.get("whiteboard_checklist") or ""
        agents_cl = st.get("agents_checklists") or []
        parts: list[str] = []
        if meta:
            parts.append(f'<b style="color:#5db9ff">Understanding</b><br>{html.escape(meta)}')
        if checklist:
            cl = html.escape(checklist).replace("\n", "<br>")
            parts.append(f'<b style="color:#9fd79f">Checklist</b><br>{cl}')
        if agents_cl:
            cl_html = []
            for a in agents_cl:
                txt = html.escape(a.get("checklist", "")).replace("\n", "<br>")
                cl_html.append(f'<b>{html.escape(a.get("id", "?"))}</b><br>{txt}')
            parts.append(
                '<b style="color:#e0b96a">Memory agents</b><br>' + "<br>".join(cl_html)
            )
        if parts:
            self.whiteboard_label.setText("<br>".join(parts))
            self.whiteboard_scroll.show()
        else:
            self.whiteboard_scroll.hide()

    # ------------------------------------------------------------- render

    def _append_user(self, text: str) -> None:
        self.chat.append(
            f'<div style="margin:10px 0;"><b style="color:#5db9ff">You</b><br>'
            f"{html.escape(text)}</div>"
        )

    def _append_assistant(
        self,
        reply: str,
        annotations: list[dict],
        saved: list[dict],
        reasoning: str = "",
    ) -> None:
        reasoning_html = ""
        if reasoning:
            r = html.escape(reasoning).replace("\n", "<br>")
            reasoning_html = (
                '<div style="margin:6px 0;padding:6px 10px;background:#1a2030;'
                'border-left:3px solid #5db9ff;color:#9fb2c8;font-size:12px;">'
                f'<b style="color:#5db9ff">Reasoning</b><br>{r}</div>'
            )
        body = html.escape(reply).replace("\n", "<br>")
        chips = ""
        if annotations:
            ids = ", ".join(a.get("memory_id", "") for a in annotations)
            chips += (
                f'<div style="margin-top:8px;">'
                f'<span style="background:#243447;color:#5db9ff;border-radius:10px;'
                f'padding:2px 8px;font-size:11px;">Remembered: {html.escape(ids)}</span></div>'
            )
        if saved:
            sids = ", ".join(r.get("id", "") for r in saved)
            chips += (
                f'<div style="margin-top:4px;">'
                f'<span style="background:#2a3a2a;color:#9fd79f;border-radius:10px;'
                f'padding:2px 8px;font-size:11px;">Saved to tape: {html.escape(sids)}</span></div>'
            )
        self.chat.append(
            f'<div style="margin:10px 0;"><b style="color:#9fd79f">Memory Machine</b><br>'
            f"{reasoning_html}{body}{chips}</div>"
        )

    def _append_system(self, text: str) -> None:
        self.chat.append(
            f'<div style="margin:6px 0;color:#8a98a8;font-size:12px;">{html.escape(text)}</div>'
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()
        self.hide()
