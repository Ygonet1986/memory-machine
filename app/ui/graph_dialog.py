"""Graph Memory viewer: read-only browse + governed review/admin actions.

The viewer never edits entities or relations directly: the only write actions
are the governed ``accept/reject/skip`` review decisions and the admin
operations that already exist in the core (rebuild/retry). Provenance always
walks back to the tape text.
"""

from __future__ import annotations

import html
import json

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..backend import Backend


def _pre(text: str) -> str:
    return f"<pre style='white-space:pre-wrap;font-size:12px'>{html.escape(text)}</pre>"


class GraphDialog(QDialog):
    def __init__(self, backend: Backend, parent=None) -> None:
        super().__init__(parent)
        self._backend = backend
        self._relations: list[dict] = []
        self.setWindowTitle("Graph Memory — Memory Machine")
        self.resize(920, 640)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_browse_tab(), "Browse")
        tabs.addTab(self._build_review_tab(), "Review")

        admin = QHBoxLayout()
        self.status_btn = QPushButton("Status")
        self.status_btn.clicked.connect(self._show_status)
        self.rebuild_btn = QPushButton("Rebuild")
        self.rebuild_btn.setToolTip("Rebuild the projection atomically; a failed rebuild keeps the current graph")
        self.rebuild_btn.clicked.connect(self._rebuild)
        self.pending_btn = QPushButton("Pending")
        self.pending_btn.clicked.connect(self._show_pending)
        self.failed_btn = QPushButton("Failed")
        self.failed_btn.clicked.connect(self._show_failed)
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.clicked.connect(self._retry)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        for button in (
            self.status_btn,
            self.rebuild_btn,
            self.pending_btn,
            self.failed_btn,
            self.retry_btn,
        ):
            admin.addWidget(button)
        admin.addStretch(1)
        admin.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        layout.addLayout(admin)

        self._show_status()

    # ------------------------------------------------------------- browse

    def _build_browse_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search entity name or alias…")
        self.search.returnPressed.connect(self._refresh_entities)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._refresh_entities)
        search_row.addWidget(QLabel("Entity"))
        search_row.addWidget(self.search, 1)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Entities"))
        self.entity_list = QListWidget()
        self.entity_list.currentRowChanged.connect(self._on_entity_selected)
        left.addWidget(self.entity_list, 2)
        left.addWidget(QLabel("Relations (select for provenance)"))
        self.relation_list = QListWidget()
        self.relation_list.currentRowChanged.connect(self._on_relation_selected)
        left.addWidget(self.relation_list, 2)
        body.addLayout(left, 1)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        body.addWidget(self.details, 2)
        layout.addLayout(body, 1)

        path_row = QHBoxLayout()
        self.path_source = QLineEdit()
        self.path_source.setPlaceholderText("source (name or E####)")
        self.path_target = QLineEdit()
        self.path_target.setPlaceholderText("target (name or E####)")
        path_btn = QPushButton("Path")
        path_btn.clicked.connect(self._show_path)
        path_row.addWidget(QLabel("Path"))
        path_row.addWidget(self.path_source, 1)
        path_row.addWidget(self.path_target, 1)
        path_row.addWidget(path_btn)
        layout.addLayout(path_row)
        return tab

    def _refresh_entities(self) -> None:
        result = self._backend.graph_entities(self.search.text().strip())
        self.entity_list.clear()
        for entity in result.get("entities", []):
            item = QListWidgetItem(
                f"{entity['name']} [{entity['id']}] · {entity.get('type', '')}"
            )
            item.setData(1000, entity["id"])
            self.entity_list.addItem(item)
        if self.entity_list.count():
            self.entity_list.setCurrentRow(0)
        else:
            self.details.setHtml(_pre(result.get("error") or "no entities"))

    def _on_entity_selected(self, row: int) -> None:
        if row < 0:
            self.relation_list.clear()
            return
        entity_id = self.entity_list.item(row).data(1000)
        result = self._backend.graph_entity(entity_id)
        self._relations = result.get("relations", [])
        self.relation_list.clear()
        for relation in self._relations:
            item = QListWidgetItem(
                f"{relation['source_name']} -{relation['relation']}-> "
                f"{relation['target_name']} · {relation['id']} · {relation['memory_id']}"
            )
            self.relation_list.addItem(item)
        entity = result.get("entity", {})
        kind = entity.get("type", "")
        canonical = result.get("canonical") or ""
        merged = (
            f"<br/><i>merged into {html.escape(canonical)}</i>"
            if canonical and canonical != entity_id
            else ""
        )
        self.details.setHtml(
            f"<h3>{html.escape(entity.get('name', entity_id))} "
            f"<span style='color:#888'>[{html.escape(entity_id)}]</span></h3>"
            f"<b>type:</b> {html.escape(kind)} · <b>from:</b> "
            f"{html.escape(entity.get('memory_id', ''))}{merged}"
            f"<p style='color:#888'>Select a relation to see its provenance chain.</p>"
        )

    def _on_relation_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._relations):
            return
        relation_id = self._relations[row]["id"]
        result = self._backend.graph_provenance(relation_id)
        if not result.get("ok"):
            self.details.setHtml(_pre(result.get("error") or "unknown relation"))
            return
        relation = result["relation"]
        memory = result.get("memory") or {}
        chain = (
            f"{relation['id']} ({relation['kind'] or 'semantic'}, "
            f"confidence {relation['confidence']})\n"
            f"  {result['source']['name'] if result.get('source') else relation['source']}\n"
            f"    -{relation['relation']}->\n"
            f"  {result['target']['name'] if result.get('target') else relation['target']}\n"
            f"  ↓\n{relation['memory_id']}\n"
            f"  ↓\n"
            f"[{memory.get('id', '?')}] {memory.get('summary', '')}\n"
            f"{memory.get('why', '')}"
        )
        self.details.setHtml(
            f"<h3>Provenance</h3>{_pre(chain)}"
            f"<p style='color:#888'>The graph selects; the tape supplies the text.</p>"
        )

    def _show_path(self) -> None:
        result = self._backend.graph_path(
            self.path_source.text().strip(), self.path_target.text().strip()
        )
        if not result.get("ok"):
            self.details.setHtml(_pre(result.get("error") or "no path"))
            return
        lines = [
            f"{result['source']['name']} → {result['target']['name']}",
            "",
        ]
        for path in result.get("paths", []):
            for detail in path.get("detail", []):
                lines.append(
                    f"{detail['source_name']} -{detail['relation']}-> {detail['target_name']} "
                    f"({detail['id']} · {detail['memory_id']} · {detail['confidence']})"
                )
            lines.append("")
        lines.append("evidence: " + ", ".join(result.get("evidence", [])))
        self.details.setHtml(f"<h3>Path</h3>{_pre(chr(10).join(lines))}")

    # ------------------------------------------------------------- review

    def _build_review_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(
            QLabel(
                "Identity hypotheses (0.60–0.90). Decisions are appended; entities "
                "are never rewritten and the tape is never touched."
            )
        )
        self.hypothesis_list = QListWidget()
        layout.addWidget(self.hypothesis_list, 1)
        row = QHBoxLayout()
        self.accept_btn = QPushButton("Accept (merge)")
        self.accept_btn.clicked.connect(lambda: self._decide("accept"))
        self.reject_btn = QPushButton("Reject")
        self.reject_btn.clicked.connect(lambda: self._decide("reject"))
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(lambda: self._decide("skip"))
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_review)
        for button in (self.accept_btn, self.reject_btn, self.skip_btn):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(refresh_btn)
        layout.addLayout(row)
        return tab

    def _refresh_review(self) -> None:
        result = self._backend.graph_review()
        self.hypothesis_list.clear()
        for hypothesis in result.get("open", []):
            item = QListWidgetItem(
                f"{hypothesis['id']} · {hypothesis.get('source_name', '')} ≈ "
                f"{hypothesis.get('target_name', '')} · {hypothesis.get('confidence', 0):.2f} "
                f"· {hypothesis.get('memory_id', '')}"
            )
            item.setData(1000, hypothesis["id"])
            self.hypothesis_list.addItem(item)

    def _decide(self, decision: str) -> None:
        item = self.hypothesis_list.currentItem()
        if item is None:
            return
        result = self._backend.graph_decide(item.data(1000), decision)
        if not result.get("ok"):
            QMessageBox.warning(self, "Review", result.get("error") or "failed")
        self._refresh_review()

    # -------------------------------------------------------------- admin

    def _show_status(self) -> None:
        result = self._backend.graph_status()
        meta = result.get("meta") or {}
        summary = (
            f"built: {result.get('built')}\n"
            f"extractor: {meta.get('extractor', '-')} {meta.get('extractor_version', '')}\n"
            f"resolver: {meta.get('resolver_version', '-')} · schema: {meta.get('schema_version', '-')}\n"
            f"counts: {json.dumps(result.get('counts', {}))}\n"
            f"pending: {result.get('pending_records', 0)}"
        )
        self.details.setHtml(f"<h3>Graph status</h3>{_pre(summary)}")

    def _rebuild(self) -> None:
        answer = QMessageBox.question(
            self,
            "Rebuild graph",
            "Re-extract every durable memory into a fresh projection?\n"
            "A failed rebuild keeps the current graph.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self._backend.graph_rebuild()
        if result.get("ok"):
            self.details.setHtml(
                f"<h3>Rebuild</h3>{_pre(json.dumps(result, indent=2, ensure_ascii=False))}"
            )
        else:
            self.details.setHtml(
                f"<h3>Rebuild failed</h3>{_pre(result.get('error', 'unknown error'))}"
                f"<p>The previous graph is intact.</p>"
            )
        self._refresh_entities()
        self._refresh_review()

    def _show_pending(self) -> None:
        result = self._backend.graph_pending()
        self.details.setHtml(
            f"<h3>Pending ({result.get('count', 0)})</h3>"
            f"{_pre(json.dumps(result.get('pending', []), indent=2, ensure_ascii=False))}"
        )

    def _show_failed(self) -> None:
        result = self._backend.graph_failed()
        self.details.setHtml(
            f"<h3>Failed ({result.get('count', 0)})</h3>"
            f"{_pre(json.dumps(result.get('failed', []), indent=2, ensure_ascii=False))}"
        )

    def _retry(self) -> None:
        result = self._backend.graph_retry()
        self.details.setHtml(
            f"<h3>Retry</h3>{_pre(json.dumps(result, indent=2, ensure_ascii=False))}"
        )
        self._refresh_review()
