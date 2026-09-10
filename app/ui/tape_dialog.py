"""Tape viewer: list, search, archive, supersede, delete and export memories."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..backend import Backend


class TapeDialog(QDialog):
    def __init__(self, backend: Backend, parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        self.setWindowTitle("Memory tape")
        self.resize(580, 500)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search memories…")
        self.search.textChanged.connect(self._refresh)

        self.list = QListWidget()

        row = QHBoxLayout()
        self.archive_btn = QPushButton("Archive")
        self.supersede_btn = QPushButton("Supersede")
        self.delete_btn = QPushButton("Delete")
        self.export_btn = QPushButton("Export…")
        self.close_btn = QPushButton("Close")
        self.archive_btn.clicked.connect(self._archive)
        self.supersede_btn.clicked.connect(self._supersede)
        self.delete_btn.clicked.connect(self._delete)
        self.export_btn.clicked.connect(self._export)
        self.close_btn.clicked.connect(self.reject)
        for b in (
            self.archive_btn,
            self.supersede_btn,
            self.delete_btn,
            self.export_btn,
            self.close_btn,
        ):
            row.addWidget(b)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addLayout(row)
        self._refresh()

    def _records(self) -> list[dict]:
        q = self.search.text().lower()
        recs = self._backend.list_memories()
        if q:
            recs = [
                r
                for r in recs
                if q
                in " ".join(
                    [str(r.get("id")), str(r.get("type")), str(r.get("summary")), str(r.get("why"))]
                ).lower()
            ]
        return recs

    def _refresh(self) -> None:
        self.list.clear()
        for r in self._records():
            status = r.get("status", "active")
            label = f'{r.get("id")} [{r.get("type")}] {r.get("summary", "")}'
            if status != "active":
                label += f"  ({status})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, r.get("id"))
            self.list.addItem(item)

    def _selected(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _archive(self) -> None:
        mid = self._selected()
        if mid and self._backend.archive_memory(mid):
            self._refresh()

    def _supersede(self) -> None:
        mid = self._selected()
        if mid and self._backend.supersede_memory(mid):
            self._refresh()

    def _delete(self) -> None:
        mid = self._selected()
        if not mid:
            return
        answer = QMessageBox.question(
            self,
            "Delete memory",
            f"Delete {mid} permanently from the tape?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes and self._backend.delete_memory(mid):
            self._refresh()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export memory", "memory.md", "Markdown (*.md)"
        )
        if not path:
            return
        res = self._backend.export_memories(path)
        QMessageBox.information(
            self, "Export", f"Exported {res.get('count', 0)} memories to {path}"
        )
