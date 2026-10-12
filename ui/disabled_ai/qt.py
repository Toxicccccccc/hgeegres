"""Binding shim: expose PyQt6 or PySide6 under one set of names.

The rest of ``lunar_v3`` imports Qt classes from here instead of a concrete
binding. That keeps the UI identical on machines that only have PySide6 (the
Python engine's dependency) and on machines with PyQt6, without a fork.
"""

from __future__ import annotations

BINDING = ""

try:  # PyQt6 first
    from PyQt6.QtCore import (  # noqa: F401
        Qt, QTimer, QSize, QPointF, QRectF, QEasingCurve, QPropertyAnimation,
        QParallelAnimationGroup, QSequentialAnimationGroup, pyqtSignal as Signal,
        pyqtProperty as Property, QObject, QEvent, QUrl, QAbstractAnimation,
    )
    from PyQt6.QtGui import (  # noqa: F401
        QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen,
        QPixmap, QPolygonF, QLinearGradient, QDesktopServices, QImage,
        QImageReader, QFontMetrics, QBrush,
    )
    from PyQt6.QtWidgets import (  # noqa: F401
        QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
        QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea, QSlider,
        QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QLineEdit, QPlainTextEdit,
        QFileDialog, QSizePolicy, QGraphicsOpacityEffect, QGraphicsDropShadowEffect,
        QMessageBox, QProgressBar, QLayout, QDialog, QMenu, QDialogButtonBox,
        QFormLayout, QToolButton, QColorDialog,
    )
    try:
        import PyQt6.QtSvg  # noqa: F401
    except ModuleNotFoundError:
        pass
    BINDING = "PyQt6"
except ModuleNotFoundError as pyqt_error:
    if pyqt_error.name != "PyQt6":
        raise
    try:
        from PySide6.QtCore import (  # noqa: F401
            Qt, QTimer, QSize, QPointF, QRectF, QEasingCurve, QPropertyAnimation,
            QParallelAnimationGroup, QSequentialAnimationGroup, Signal,
            Property, QObject, QEvent, QUrl, QAbstractAnimation,
        )
        from PySide6.QtGui import (  # noqa: F401
            QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen,
            QPixmap, QPolygonF, QLinearGradient, QDesktopServices, QImage,
            QImageReader, QFontMetrics, QBrush,
        )
        from PySide6.QtWidgets import (  # noqa: F401
            QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
            QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea, QSlider,
            QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QLineEdit,
            QPlainTextEdit, QFileDialog, QSizePolicy, QGraphicsOpacityEffect,
            QGraphicsDropShadowEffect, QMessageBox, QProgressBar, QLayout,
            QDialog, QMenu, QDialogButtonBox, QFormLayout, QToolButton, QColorDialog,
        )
        try:
            import PySide6.QtSvg  # noqa: F401
        except ModuleNotFoundError:
            pass
        BINDING = "PySide6"
    except ModuleNotFoundError as pyside_error:
        if pyside_error.name != "PySide6":
            raise
        raise ModuleNotFoundError(
            "The desktop GUI requires PyQt6 or PySide6. Install one with "
            "'python -m pip install PyQt6' using the interpreter that launches "
            "the GUI."
        ) from pyside_error
