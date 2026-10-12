"""Disabled AI — single entry point.

Run this from anywhere:   python run_app.py   (or double-click run.bat)

Everything lives under clear top-level folders:

    app/        desktop shell helpers (profiles, model converter, quick menu)
    engine/     the detection + assist engine (Python and native backends)
    ui/         the Disabled AI interface
    assets/     icons, fonts and game cover art
    config/     saved settings and per-game profiles
    models/     YOLO weights (.pt / .onnx / .engine)
    firmware/   Arduino sketch, opened as firmware/mouse/mouse.ino
    tools/      converter scripts and launchers
    tests/      automated checks
    docs/       documentation and reference material
"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The engine and the UI each import their own neighbours by module name, so both
# trees are on the path. Keeping this list short makes the search order obvious.
for folder in (ROOT, ROOT / "engine", ROOT / "app", ROOT / "ui", ROOT / "ui" / "disabled_ai"):
    path = str(folder)
    if path not in sys.path:
        sys.path.insert(0, path)


def _install_exception_guard() -> None:
    """Turn an unhandled exception into a logged error instead of a crash.

    Qt runs slots inside its C++ event loop, and PySide6 cannot propagate a
    Python exception back out through it: the interpreter aborts the whole
    process (Windows error 0xC0000409). That made any single bad slot -- a
    missing attribute, a frame of the wrong type -- kill the app with no
    message. Exceptions are now printed with a traceback so the app survives
    and the reason is visible in the console.
    """

    def _hook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def main() -> int:
    _install_exception_guard()

    from qt import QApplication
    import theme
    from main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Disabled AI")
    theme.apply(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
