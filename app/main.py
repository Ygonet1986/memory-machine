"""Memory Machine desktop app — entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .backend import Backend
from .icon import icon
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Memory Machine")
    app.setQuitOnLastWindowClosed(False)

    backend = Backend()
    window = MainWindow(backend)

    tray = QSystemTrayIcon(icon(), app)
    tray.setToolTip("Memory Machine")
    menu = QMenu()
    open_action = QAction("Open", menu)
    open_action.triggered.connect(lambda: window.showNormal() or window.raise_())
    new_topic_action = QAction("New topic", menu)
    new_topic_action.triggered.connect(lambda: (window.showNormal(), window._new_topic()))

    from .companion_launcher import open_companion

    companion_action = QAction("Companion", menu)
    companion_action.triggered.connect(open_companion)
    menu.addAction(companion_action)

    settings_action = QAction("Settings", menu)
    settings_action.triggered.connect(window._open_settings)
    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(open_action)
    menu.addAction(new_topic_action)
    menu.addAction(settings_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: window.showNormal() or window.raise_()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    window.show()

    if not backend.configured():
        from .ui.settings_dialog import SettingsDialog

        SettingsDialog(window).exec()
        backend.reload()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
