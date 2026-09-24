"""Creator dialog: gallery, sheet, life timeline, revision, retire (C5c).

Thin Qt layer over :class:`app.companion_creator_backend.CreatorBackend`.
Events are edited through a structured form (no JSON); advanced link editing
(causes/effects) stays out of the first cut.
"""

from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from memory_machine.companion_gallery import life_timeline

from ..companion_creator_backend import CreatorBackend

PRECISIONS = ("day", "month", "year", "unknown")


class EventDialog(QDialog):
    def __init__(self, parent=None, *, event: dict[str, Any] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Evento da vida")
        self.resize(460, 360)
        form = QFormLayout(self)
        self.title_edit = QLineEdit((event or {}).get("title", ""))
        self.summary_edit = QPlainTextEdit((event or {}).get("summary", ""))
        self.summary_edit.setFixedHeight(90)
        self.time_edit = QLineEdit((event or {}).get("event_time", ""))
        self.time_edit.setPlaceholderText("2018, 2018-06 ou 2018-06-10")
        self.precision_combo = QComboBox()
        self.precision_combo.addItems(PRECISIONS)
        current = (event or {}).get("time_precision", "day")
        if current in PRECISIONS:
            self.precision_combo.setCurrentText(current)
        self.place_edit = QLineEdit((event or {}).get("place", ""))
        form.addRow("Título", self.title_edit)
        form.addRow("Resumo", self.summary_edit)
        form.addRow("Data", self.time_edit)
        form.addRow("Precisão", self.precision_combo)
        form.addRow("Lugar", self.place_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, Any]:
        return {
            "title": self.title_edit.text().strip(),
            "summary": self.summary_edit.toPlainText().strip(),
            "event_time": self.time_edit.text().strip(),
            "time_precision": self.precision_combo.currentText(),
            "place": self.place_edit.text().strip(),
        }


class CreatorDialog(QDialog):
    def __init__(self, backend: CreatorBackend, parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._person = ""
        self._character = ""
        self._draft: dict[str, Any] | None = None
        self._self_id = "lia"
        self.setWindowTitle("Personagens — criador")
        self.resize(980, 660)
        self._build_ui()
        self._refresh_relationships()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Relações"))
        self.relationship_list = QListWidget()
        self.relationship_list.itemSelectionChanged.connect(self._open_selected)
        left_layout.addWidget(self.relationship_list, 1)
        row = QHBoxLayout()
        new_btn = QPushButton("Nova…")
        new_btn.clicked.connect(self._new_character)
        copy_btn = QPushButton("Copiar…")
        copy_btn.clicked.connect(self._copy_character)
        row.addWidget(new_btn)
        row.addWidget(copy_btn)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.tabs = QTabWidget()
        self.sheet_label = QLabel()
        self.sheet_label.setWordWrap(True)
        self.sheet_label.setTextFormat(Qt.TextFormat.RichText)
        self.sheet_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tabs.addTab(self.sheet_label, "Ficha")

        life_tab = QWidget()
        life_layout = QVBoxLayout(life_tab)
        self.life_list = QListWidget()
        life_layout.addWidget(self.life_list, 1)
        life_row = QHBoxLayout()
        for label, handler in (
            ("Adicionar…", self._add_event),
            ("Editar…", self._edit_event),
            ("Aprovar evento", self._approve_event),
            ("Remover do rascunho", self._remove_event),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            life_row.addWidget(button)
        life_layout.addLayout(life_row)
        action_row = QHBoxLayout()
        for label, handler in (
            ("Salvar rascunho", self._save_draft),
            ("Diferenças…", self._show_diff),
            ("Aprovar versão e publicar", self._approve_version),
            ("Retirar publicado…", self._retire),
            ("Impacto…", self._show_impact),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            action_row.addWidget(button)
        life_layout.addLayout(action_row)
        self.tabs.addTab(life_tab, "Vida")
        right_layout.addWidget(self.tabs)
        splitter.addWidget(right)
        splitter.setSizes([260, 720])
        wrapper = QVBoxLayout(self)
        wrapper.addWidget(splitter)

    def _selected_relationship(self) -> dict[str, Any] | None:
        item = self.relationship_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _refresh_relationships(self) -> None:
        self.relationship_list.clear()
        for row in self._backend.relationships():
            item = QListWidgetItem(f"{row['name']} · {row['character']} "
                                   f"(ficha v{row['persona_version']}, "
                                   f"vida v{row['life_version']})")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.relationship_list.addItem(item)

    # ------------------------------------------------------------ creation

    def _new_character(self) -> None:
        templates = [row["slug"] for row in self._backend.templates()
                     if row["life_versions"]]
        if not templates:
            QMessageBox.warning(self, "Personagens", "Nenhum template disponível.")
            return
        slug, ok = QInputDialog.getItem(self, "Nova personagem",
                                        "Template:", templates, 0, False)
        if not ok:
            return
        character, ok = QInputDialog.getText(self, "Nova personagem",
                                             "ID da personagem (a-z, 0-9):")
        if not ok or not character.strip():
            return
        result = self._backend.create("local", character.strip(), slug)
        self._finish(result, "Personagem criada")

    def _copy_character(self) -> None:
        selected = self._selected_relationship()
        if not selected:
            return
        new_id, ok = QInputDialog.getText(self, "Copiar personagem",
                                          "Novo ID (sem conversas herdadas):")
        if not ok or not new_id.strip():
            return
        result = self._backend.copy(selected["person"], selected["character"],
                                    new_id.strip())
        self._finish(result, "Personagem copiada")

    def _finish(self, result: dict[str, Any], success: str) -> None:
        if not result.get("ok"):
            QMessageBox.warning(self, "Personagens", str(result.get("error")))
            return
        self._refresh_relationships()
        self._refresh_life()
        QMessageBox.information(self, "Personagens", success)

    # ---------------------------------------------------------- open state

    def _open_selected(self) -> None:
        selected = self._selected_relationship()
        if not selected:
            return
        self._person = selected["person"]
        self._character = selected["character"]
        state = self._backend.open(self._person, self._character)
        if not state.get("ok"):
            QMessageBox.warning(self, "Personagens", str(state.get("error")))
            return
        sheet = state["persona"]
        self.sheet_label.setText(
            f"<b>{html.escape(sheet['name'])} v{sheet['version']}</b><br>"
            f"<i>{html.escape(sheet['voice'])}</i><br><br>"
            + "<br>".join(f"• {html.escape(item)}" for item in sheet["values"])
            + "<br><br><b>Biografia</b><br>"
            + "<br>".join(f"• {html.escape(item)}" for item in sheet["bio"]))
        self._refresh_life()

    def _refresh_life(self) -> None:
        self.life_list.clear()
        if not self._character:
            return
        draft = self._backend.draft(self._person, self._character)
        if not draft.get("ok"):
            self._draft = None
            return
        self._draft = draft["draft"]
        self._self_id = self._self_id_from_draft()
        for entry in life_timeline(self._draft):
            marker = "✔" if entry["status"] == "approved" else (
                "—" if entry["status"] == "retired" else "•")
            item = QListWidgetItem(
                f"{marker} {entry['event_time'] or 'sem data'} · "
                f"{entry['title']} [{entry['status']}]")
            item.setData(Qt.ItemDataRole.UserRole, entry["event_id"])
            item.setToolTip(entry["summary"])
            self.life_list.addItem(item)

    def _self_id_from_draft(self) -> str:
        if self._draft is None:
            return "lia"
        people = {person["id"] for person in self._draft["world"]["people"]}
        for event in self._draft["events"]:
            for item in event["participants"]:
                if item["id"] not in people:
                    return item["id"]
        return "lia"

    def _selected_event(self) -> str:
        item = self.life_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    # ----------------------------------------------------------- editing

    def _event_by_id(self, event_id: str) -> dict[str, Any] | None:
        if self._draft is None:
            return None
        return next((event for event in self._draft["events"]
                     if event["event_id"] == event_id), None)

    def _add_event(self) -> None:
        if self._draft is None:
            return
        dialog = EventDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["title"] or not values["summary"]:
            QMessageBox.warning(self, "Vida", "Título e resumo são obrigatórios.")
            return
        next_id = 1 + max((int(event["event_id"].split("-")[-1])
                           for event in self._draft["events"]), default=0)
        self._draft["events"].append({
            "event_id": f"life-{next_id:04d}",
            "life_version": self._draft["life_version"],
            **values,
            "participants": [{"id": self._self_id, "role": ""}],
            "causes": [], "effects": [],
            "status": "draft", "approved_at": "", "approved_by": "",
            "provenance": {"kind": "synthetic_life",
                           "generator": "manual",
                           "sheet_version": self._draft["sheet_version"],
                           "prompt": "", "model": "", "seed": ""},
        })
        self._refresh_life()

    def _edit_event(self) -> None:
        event = self._event_by_id(self._selected_event())
        if event is None:
            return
        dialog = EventDialog(self, event=event)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        event.update(dialog.values())
        self._refresh_life()

    def _approve_event(self) -> None:
        event = self._event_by_id(self._selected_event())
        if event is None:
            return
        from datetime import datetime, timezone

        event["status"] = "approved"
        event["approved_at"] = datetime.now(timezone.utc).isoformat()
        event["approved_by"] = "owner"
        self._refresh_life()

    def _remove_event(self) -> None:
        event_id = self._selected_event()
        if self._draft is None or not event_id:
            return
        self._draft["events"] = [event for event in self._draft["events"]
                                 if event["event_id"] != event_id]
        links = {event["event_id"] for event in self._draft["events"]}
        for event in self._draft["events"]:
            event["causes"] = [i for i in event["causes"] if i in links]
            event["effects"] = [i for i in event["effects"] if i in links]
        self._refresh_life()

    # --------------------------------------------------------- publishing

    def _save_draft(self) -> None:
        if self._draft is None:
            return
        result = self._backend.save_draft(self._person, self._character,
                                          self._draft)
        if not result.get("ok"):
            QMessageBox.warning(self, "Rascunho", str(result.get("error")))
            return
        QMessageBox.information(self, "Rascunho", "Rascunho salvo.")

    def _show_diff(self) -> None:
        result = self._backend.diff(self._person, self._character)
        if not result.get("ok"):
            QMessageBox.warning(self, "Diferenças", str(result.get("error")))
            return
        diff = result["diff"]
        lines = [f"v{diff['old_version']} → v{diff['new_version']}",
                 f"adicionados: {', '.join(diff['added']) or '—'}",
                 f"removidos: {', '.join(diff['removed']) or '—'}"]
        for event_id, fields in diff["changed"].items():
            lines.append(f"{event_id}: {', '.join(fields)}")
        QMessageBox.information(self, "Diferenças", "\n".join(lines))

    def _approve_version(self) -> None:
        if self._draft is None:
            return
        confirm = QMessageBox.question(
            self, "Aprovar versão",
            "Aprovar esta versão e publicar os eventos aprovados na fita?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        result = self._backend.approve(self._person, self._character,
                                       self._draft)
        if not result.get("ok"):
            QMessageBox.warning(self, "Aprovar", str(result.get("error")))
            return
        published = result.get("published") or {}
        QMessageBox.information(
            self, "Aprovar",
            f"v{result['life_version']} publicada: "
            f"{len(published.get('admitted', []))} eventos, "
            f"{len(published.get('superseded', []))} substituídos.")
        self._refresh_relationships()
        self._refresh_life()

    def _show_impact(self) -> None:
        event_id = self._selected_event()
        if not event_id:
            return
        result = self._backend.impact(self._person, self._character, event_id)
        if not result.get("event_id"):
            QMessageBox.warning(self, "Impacto", str(result.get("error")))
            return
        text = [f"evento: {event_id}",
                f"registro: {result['target']['record_id'] or '—'} "
                f"({'ativo' if result['target']['active'] else 'inativo'})",
                f"derivados: {', '.join(result['derived']) or '—'}",
                f"possíveis menções: {', '.join(result['mentions']) or '—'}"]
        QMessageBox.information(self, "Impacto", "\n".join(text))

    def _retire(self) -> None:
        event_id = self._selected_event()
        if not event_id:
            return
        confirm = QMessageBox.question(
            self, "Retirar evento",
            f"Retirar {event_id}? Uma nova versão será publicada e o evento "
            "deixa de ser lembrado (o histórico administrativo fica).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        result = self._backend.retire(self._person, self._character, event_id)
        if not result.get("ok"):
            QMessageBox.warning(self, "Retirar", str(result.get("error")))
            return
        self._refresh_relationships()
        self._refresh_life()
