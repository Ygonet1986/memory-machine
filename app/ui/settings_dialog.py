"""Settings dialog: API key, model, base URL and memory root."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from ..settings import load_settings, save_settings


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — Memory Machine")
        self.setMinimumWidth(420)

        settings = load_settings()

        self.api_key = QLineEdit(settings.get("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-...")

        self.model = QLineEdit(settings.get("model", "deepseek-v4-flash"))
        self.base_url = QLineEdit(settings.get("base_url", "https://api.deepseek.com"))
        self.memory_root = QLineEdit(settings.get("memory_root", ""))

        self.auto_topic = QComboBox()
        self.auto_topic.addItem("One topic per day", "day")
        self.auto_topic.addItem("New topic after idle", "idle")
        self.auto_topic.addItem("Off (manual)", "off")
        current = settings.get("auto_topic", "day")
        idx = self.auto_topic.findData(current)
        self.auto_topic.setCurrentIndex(idx if idx >= 0 else 0)

        self.web_search = QComboBox()
        self.web_search.addItem("Auto (when the question needs it)", "auto")
        self.web_search.addItem("Off", "off")
        self.web_search.addItem("Always", "always")
        web_current = settings.get("web_search", "auto")
        widx = self.web_search.findData(web_current)
        self.web_search.setCurrentIndex(widx if widx >= 0 else 0)

        self.memory_mode = QComboBox()
        self.memory_mode.addItem("Partition agents (default)", "partition")
        self.memory_mode.addItem("View agents", "view")
        self.memory_mode.addItem("View agents + dimension boards", "view_boards")
        mode_current = settings.get("memory_mode", "partition")
        midx = self.memory_mode.findData(mode_current)
        self.memory_mode.setCurrentIndex(midx if midx >= 0 else 0)

        form = QFormLayout()
        form.addRow("DeepSeek API key", self.api_key)
        form.addRow("Model", self.model)
        form.addRow("Base URL", self.base_url)
        form.addRow("Auto topic", self.auto_topic)
        form.addRow("Web search", self.web_search)
        form.addRow("Memory mode", self.memory_mode)
        form.addRow("Memory root", self.memory_root)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        save_settings(
            {
                "api_key": self.api_key.text().strip(),
                "model": self.model.text().strip() or "deepseek-v4-flash",
                "base_url": self.base_url.text().strip() or "https://api.deepseek.com",
                "memory_root": self.memory_root.text().strip(),
                "auto_topic": self.auto_topic.currentData(),
                "web_search": self.web_search.currentData(),
                "memory_mode": self.memory_mode.currentData(),
            }
        )
        self.accept()
