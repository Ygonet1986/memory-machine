"""Companion window: chat with the approved persona + "What I remember".

Thin Qt layer over :class:`app.companion_backend.CompanionBackend`; all the
logic that can be tested lives in the backend. First run shows the Lia v1
sheet for approval; the panel lists the four chat memory kinds with correct
(supersession) and delete (cascade, with the linked-deletion disclosure).
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..companion_backend import CompanionBackend
from .main_window import InputBox

TYPE_LABELS = {
    "person_report": "Relato",
    "episode": "Episódio",
    "story": "História",
    "hypothesis": "Hipótese",
}


class TurnWorker(QThread):
    ok = Signal(dict)
    err = Signal(str)

    def __init__(self, backend: CompanionBackend, message: str, save: bool,
                 parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._message = message
        self._save = save

    def run(self) -> None:  # noqa: D102 (Qt override)
        try:
            self.ok.emit(self._backend.turn(self._message, save=self._save))
        except Exception as error:  # noqa: BLE001
            self.err.emit(str(error))


class CompanionWindow(QMainWindow):
    def __init__(self, backend: CompanionBackend) -> None:
        super().__init__()
        self._backend = backend
        self._worker: TurnWorker | None = None
        self.setWindowTitle("Memory Machine Companion — Lia")
        self.resize(940, 660)
        self._build_ui()
        self._refresh_persona()
        self._refresh_memories()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        self.persona_label = QLabel()
        self.persona_label.setWordWrap(True)
        self.persona_label.setTextFormat(Qt.TextFormat.RichText)
        self.persona_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        left_layout.addWidget(self.persona_label)

        self.approve_btn = QPushButton("Aprovar a Lia v1")
        self.approve_btn.clicked.connect(self._approve)
        left_layout.addWidget(self.approve_btn)

        self.chat = QTextBrowser()
        self.chat.setStyleSheet(
            "QTextBrowser { background: #14181f; color: #e8eef7; border: none; "
            "font-size: 14px; }"
        )
        left_layout.addWidget(self.chat, 1)

        self.input = InputBox()
        self.input.setPlaceholderText(
            "Escreva para a Lia… (Enter envia, Shift+Enter quebra linha)")
        self.input.setStyleSheet(
            "QPlainTextEdit { background: #1b2129; color: #e8eef7; border: 1px "
            "solid #263041; border-radius: 6px; padding: 6px; }"
        )
        self.input.setFixedHeight(84)
        self.input.submitted.connect(self._send)
        left_layout.addWidget(self.input)

        row = QHBoxLayout()
        self.quiet = QCheckBox("Não guardar esta conversa")
        self.quiet.setToolTip(
            "O turno roda numa cópia temporária; nada novo é gravado no root.")
        self.quiet.toggled.connect(self._refresh_mode)
        row.addWidget(self.quiet)
        self.mode_label = QLabel()
        row.addWidget(self.mode_label, 1)
        self.send_btn = QPushButton("Enviar")
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("O que eu lembro"))
        self.memory_list = QListWidget()
        self.memory_list.setStyleSheet(
            "QListWidget { background: #14181f; color: #e8eef7; border: 1px "
            "solid #263041; border-radius: 6px; }"
        )
        right_layout.addWidget(self.memory_list, 1)
        buttons = QHBoxLayout()
        self.correct_btn = QPushButton("Corrigir")
        self.correct_btn.clicked.connect(self._correct)
        self.delete_btn = QPushButton("Apagar")
        self.delete_btn.clicked.connect(self._delete)
        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self._refresh_memories)
        for button in (self.correct_btn, self.delete_btn, self.refresh_btn):
            buttons.addWidget(button)
        right_layout.addLayout(buttons)
        hint = QLabel(
            "Apagar remove também o turno de origem e o que derivou dele.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a98a8; font-size: 11px;")
        right_layout.addWidget(hint)
        splitter.addWidget(right)
        splitter.setSizes([620, 320])

        self.setCentralWidget(splitter)
        self._refresh_mode()

    def _refresh_mode(self) -> None:
        if self.quiet.isChecked():
            self.mode_label.setText("Modo: não guardar (cópia temporária).")
            self.mode_label.setStyleSheet("color: #d7a86b; font-size: 11px;")
        else:
            self.mode_label.setText("Modo: guardando novas lembranças.")
            self.mode_label.setStyleSheet("color: #8a98a8; font-size: 11px;")

    # -------------------------------------------------------------- persona

    def _refresh_persona(self) -> None:
        sheet = self._backend.persona()
        if sheet is None:
            self.persona_label.setText(
                "<b>Lia (personagem original)</b> — aprove a ficha para começar. "
                "Ela é ficcional; a biografia não é um fato sobre você."
            )
            self.approve_btn.setVisible(True)
            return
        bio = "".join(f"<li>{html.escape(item)}</li>" for item in sheet["bio"])
        self.persona_label.setText(
            f"<b>{html.escape(sheet['name'])} v{sheet['version']}</b> aprovada. "
            f"<span style='color:#8a98a8'>{html.escape(sheet['voice'])}</span>"
            f"<ul style='margin:6px 0 0 16px;color:#9fb2c8;font-size:12px'>{bio}</ul>"
        )
        self.approve_btn.setVisible(False)

    def _approve(self) -> None:
        result = self._backend.approve_persona()
        if not result.get("ok"):
            QMessageBox.warning(self, "Persona", str(result.get("error")))
            return
        self._refresh_persona()
        self._refresh_memories()
        self._append_system("Lia v1 aprovada. Biografia ficcional registrada.")

    # ----------------------------------------------------------------- chat

    def _send(self) -> None:
        if self._worker is not None:
            return
        if self._backend.persona() is None:
            self._append_system("Aprove a ficha da Lia para começar.")
            return
        message = self.input.toPlainText().strip()
        if not message:
            return
        self.input.clear()
        self._append_user(message)
        save = not self.quiet.isChecked()
        self._set_busy(True)
        self._worker = TurnWorker(self._backend, message, save, parent=self)
        self._worker.ok.connect(self._on_ok)
        self._worker.err.connect(self._on_err)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_ok(self, result: dict) -> None:
        if not result.get("ok"):
            self._append_system(f"Erro: {result.get('error')}")
            return
        used = ", ".join(item["memory_id"] for item in result.get("used") or [])
        chips = f" · lembrou: {html.escape(used)}" if used else ""
        if result.get("saved") is None:
            chips += " · não guardado"
        self._append_assistant(result.get("reply", ""), chips)
        self._refresh_memories()

    def _on_err(self, message: str) -> None:
        self._append_system(f"Erro: {message}")

    def _on_done(self) -> None:
        self._worker = None
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.send_btn.setEnabled(not busy)
        self.input.setReadOnly(busy)
        self.send_btn.setText("…" if busy else "Enviar")

    def _append_user(self, text: str) -> None:
        self.chat.append(
            f'<div style="margin:10px 0;"><b style="color:#5db9ff">Você</b><br>'
            f"{html.escape(text)}</div>"
        )

    def _append_assistant(self, reply: str, chips: str = "") -> None:
        body = html.escape(reply).replace("\n", "<br>")
        self.chat.append(
            f'<div style="margin:10px 0;"><b style="color:#9fd79f">Lia</b><br>'
            f"{body}<div style='margin-top:6px;color:#8a98a8;font-size:11px'>"
            f"{chips}</div></div>"
        )

    def _append_system(self, text: str) -> None:
        self.chat.append(
            f'<div style="margin:6px 0;color:#8a98a8;font-size:12px;">'
            f"{html.escape(text)}</div>"
        )

    # ---------------------------------------------------------------- panel

    def _refresh_memories(self) -> None:
        self.memory_list.clear()
        for row in self._backend.memories():
            label = TYPE_LABELS.get(row["type"], row["type"])
            origin = row.get("origin") or {}
            source = str(origin.get("kind") or "")
            if origin.get("version"):
                source += f":{origin['version']}"
            if origin.get("event_id"):
                source += f":{origin['event_id']}"
            item = QListWidgetItem(
                f"{label} · {row['summary']}  ({source or 'sem fonte'})"
            )
            item.setData(Qt.ItemDataRole.UserRole, row["memory_id"])
            self.memory_list.addItem(item)

    def _selected_id(self) -> str:
        item = self.memory_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def _correct(self) -> None:
        memory_id = self._selected_id()
        if not memory_id:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Corrigir lembrança",
            "Nova versão (a antiga fica no histórico, fora do recall):",
        )
        if not ok or not text.strip():
            return
        result = self._backend.correct(memory_id, text)
        if not result.get("ok"):
            QMessageBox.warning(self, "Corrigir", str(result.get("error")))
            return
        self._refresh_memories()
        self._append_system(f"Corrigido: {memory_id} → {result['record']['memory_id']}")

    def _delete(self) -> None:
        memory_id = self._selected_id()
        if not memory_id:
            return
        confirm = QMessageBox.question(
            self, "Apagar lembrança",
            f"Apagar {memory_id}? Isso remove também o turno de origem e os "
            "registros derivados (resumos). Não dá para desfazer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        result = self._backend.delete(memory_id)
        if not result.get("ok"):
            QMessageBox.warning(self, "Apagar", str(result.get("error")))
            return
        self._refresh_memories()
        removed = ", ".join(result.get("removed") or [])
        self._append_system(f"Apagado: {removed}")
