"""
Inchro — PyQt6 front-end for the Inchro C++ backend.

Edits config.json and launches/stops Inchro.exe. Auth is handled by the
backend; this UI prompts for credentials when login is required or the
session expires. Run:  python main.py
"""

import sys
import traceback

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from main_window import MainWindow


def _install_excepthook():
    def _hook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb)
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = _hook


def main():
    _install_excepthook()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Inchro")

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
