"""The Profiles page: one cover-art card per saved game profile.

A profile stores the whole settings bundle for one game, so switching game is a
single click instead of re-tuning every slider. The grid fetches cover art on
first use (with a drawn fallback when offline) and repaints as it arrives.
"""

from __future__ import annotations

from qt import (
    Qt, QTimer, QSize, QRectF, QPainter, QColor, QPen, QPixmap, QPainterPath,
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QLineEdit, QDialog, QMessageBox, QFileDialog, QFrame,
    QCheckBox,
)

import theme
from game_art import render_cover_only, draw_card_footer, render_game_art, prefetch_all, clear_cache
from game_catalog import GAMES, GameInfo, get_game, search_games
from profiles import ProfileEntry, ProfileManager

CARD_W = 126
CARD_H = 224
CARD_RADIUS = 18
GRID_GAP = 16


def _rounded_path(rect, radius):
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    return path


class _CardButton(QPushButton):
    """A flat, transparent button used as a card surface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setFixedSize(CARD_W, CARD_H)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; margin: 0; }"
            "QPushButton:hover { background: rgba(255,255,255,0.04); border-radius: 18px; }"
        )


def _paint_card(p, rect, cover, title, accent, *, border="#2f2f2f", width=1, pad=1):
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.setPen(QPen(QColor(border), width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

    inner = rect.adjusted(pad, pad, -pad, -pad)
    p.setClipPath(_rounded_path(inner, CARD_RADIUS - 2))
    scaled = cover.scaled(inner.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
    x = inner.x() + (inner.width() - scaled.width()) // 2
    y = inner.y() + (inner.height() - scaled.height()) // 2
    p.drawPixmap(x, y, scaled)
    p.setClipping(False)
    draw_card_footer(p, inner, title, accent, CARD_RADIUS - 2)


class GameCard(_CardButton):
    """A game, ready to have a profile created for it."""

    def __init__(self, game: GameInfo, parent=None):
        super().__init__(parent)
        self.game = game
        self._cover = render_cover_only(game, CARD_W - 4, CARD_H - 4)
        self.setToolTip(f"Create a profile for {game.name}")

    def paintEvent(self, _event):
        p = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        _paint_card(p, rect, self._cover, self.game.name, self.game.accent, border="#3a3a3a")
        p.end()


class ProfileCard(_CardButton):
    """A saved profile: click to load, right-click to edit or delete."""

    def __init__(self, entry: ProfileEntry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._game = get_game(entry.game_id) or GameInfo(
            entry.game_id, entry.display_name, "#27272a", "#52525b", theme.ACCENT)
        self._cover = render_cover_only(self._game, CARD_W - 4, CARD_H - 4)
        self.setToolTip(f"{entry.filename}\nClick to load · Right-click to edit or delete")

    def paintEvent(self, _event):
        p = QPainter(self)
        rect = self.rect().adjusted(1, 1, -1, -1)
        active = self.entry.active
        _paint_card(
            p, rect, self._cover, self.entry.label, self._game.accent,
            border=theme.GOOD if active else "#2f2f2f",
            width=3 if active else 1,
            pad=3 if active else 1,
        )
        inner = rect.adjusted(3 if active else 1, 3 if active else 1,
                              -(3 if active else 1), -(3 if active else 1))
        if self.entry.has_model:
            p.setBrush(QColor(theme.ACCENT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(inner.left() + 8, inner.top() + 8, 10, 10)
        p.end()

    def contextMenuEvent(self, event):
        from qt import QMenu
        menu = QMenu(self)
        edit = menu.addAction("Edit…")
        delete = menu.addAction("Delete…")
        chosen = menu.exec(event.globalPos())
        if chosen == edit:
            self.edit_requested = True
            self.parent().parent()._edit_profile(self.entry)
        elif chosen == delete:
            self.parent().parent()._delete_profile(self.entry)


class AddCard(_CardButton):
    """The dashed '+' card that starts the create-a-profile flow."""

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(QColor("#141828"))
        p.setPen(QPen(QColor("#3a3a5a"), 2, Qt.PenStyle.DashLine))
        p.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        p.setPen(QPen(QColor(theme.ACCENT), 2.5))
        cx, cy = rect.center().x(), rect.center().y()
        arm = 22
        p.drawLine(cx - arm, cy, cx + arm, cy)
        p.drawLine(cx, cy - arm, cx, cy + arm)
        p.end()


class GamePickerDialog(QDialog):
    """Pick a game to create a profile for."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose a game")
        self.setModal(True)
        self.resize(780, 640)
        self.selected: GameInfo | None = None
        self._build()
        QTimer.singleShot(0, self._load_covers)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("Pick a game for this profile")
        title.setStyleSheet("font-size: 15pt; font-weight: 800;")
        root.addWidget(title)

        hint = QLabel("Each profile stores your full settings for that game.")
        hint.setObjectName("hint")
        root.addWidget(hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games…")
        self.search.textChanged.connect(lambda *_: self._refresh())
        root.addWidget(self.search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setHorizontalSpacing(GRID_GAP)
        self.grid.setVerticalSpacing(GRID_GAP)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        root.addLayout(row)
        self._refresh()

    def _load_covers(self):
        prefetch_all()
        clear_cache()
        self._refresh()

    def _refresh(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        columns = 5
        for index, game in enumerate(search_games(self.search.text())):
            card = GameCard(game)
            card.clicked.connect(lambda _=False, g=game: self._pick(g))
            self.grid.addWidget(card, index // columns, index % columns)

    def _pick(self, game: GameInfo):
        self.selected = game
        self.accept()


class ProfilesPage(QWidget):
    """The page itself: status line + responsive grid of profile cards."""

    def __init__(self, manager: ProfileManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._last_columns = 0
        self._build()
        QTimer.singleShot(0, self._prefetch)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 24)
        outer.setSpacing(10)

        heading = QLabel("Profiles")
        heading.setObjectName("tabHeader")
        outer.addWidget(heading)

        sub = QLabel("One profile per game. Save your settings once, then switch game in a click.")
        sub.setObjectName("hint")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        status = QHBoxLayout()
        self.active_label = QLabel("")
        self.active_label.setStyleSheet(f"color: {theme.GOOD}; font-weight: 700;")
        status.addWidget(self.active_label, 1)
        outer.addLayout(status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 8, 0, 8)
        self.grid.setHorizontalSpacing(GRID_GAP)
        self.grid.setVerticalSpacing(GRID_GAP)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    def _prefetch(self):
        prefetch_all()
        clear_cache()
        self.refresh(force=True)

    def _update_status(self):
        active = self.manager.active_filename()
        self.active_label.setText(f"Active profile: {active}" if active else "No profile loaded")

    def refresh(self, *, force: bool = False):
        columns = max(3, (max(self.width(), 640) - 140) // (CARD_W + GRID_GAP))
        if not force and columns == self._last_columns and self.grid.count() > 0:
            self._update_status()
            return
        self._last_columns = columns

        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._update_status()

        add = AddCard()
        add.setToolTip("Create a profile for a game")
        add.clicked.connect(self._on_add)
        self.grid.addWidget(add, 0, 0)

        for index, entry in enumerate(self.manager.list_profiles()):
            card = ProfileCard(entry)
            card.clicked.connect(lambda _=False, e=entry: self._on_load(e))
            self.grid.addWidget(card, (index + 1) // columns, (index + 1) % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    # ---- actions -----------------------------------------------------------
    def _on_add(self):
        picker = GamePickerDialog(self)
        if picker.exec() != QDialog.DialogCode.Accepted or not picker.selected:
            return
        game = picker.selected
        answer = QMessageBox.question(
            self, game.name,
            f"Create a profile for {game.name}?\n\n"
            "Yes = start from your current settings.\n"
            "No = start from fresh defaults.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return
        try:
            if answer == QMessageBox.StandardButton.Yes:
                self.manager.save_current_as(game.id, game.name)
            else:
                self.manager.create_fresh(game.id, game.name)
        except OSError as exc:
            QMessageBox.critical(self, "Profiles", f"Could not save the profile:\n{exc}")
            return
        self.refresh(force=True)

    def _on_load(self, entry: ProfileEntry):
        try:
            self.manager.activate(entry.filename, force=True)
        except OSError as exc:
            QMessageBox.critical(self, "Profiles", f"Could not load the profile:\n{exc}")
            return
        self.refresh(force=True)

    def _edit_profile(self, entry: ProfileEntry):
        dialog = ProfileEditDialog(self.manager, entry, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh(force=True)

    def _delete_profile(self, entry: ProfileEntry):
        answer = QMessageBox.question(
            self, "Delete profile", f"Delete {entry.label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.manager.delete(entry.filename)
        except OSError as exc:
            QMessageBox.critical(self, "Profiles", f"Could not delete the profile:\n{exc}")
            return
        self.refresh(force=True)


class ProfileEditDialog(QDialog):
    """Rename a profile (via its label file), toggle auto-save/auto-load, set a model."""

    def __init__(self, manager: ProfileManager, entry: ProfileEntry, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.entry = entry
        self.game = get_game(entry.game_id) or GameInfo(
            entry.game_id, entry.display_name, "#27272a", "#52525b", theme.ACCENT)
        self.setWindowTitle(f"Edit — {entry.label}")
        self.setModal(True)
        self.resize(440, 600)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 22)
        lay.setSpacing(10)

        art = QLabel()
        art.setPixmap(render_game_art(self.game, 180, 320))
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(art)

        title = QLabel(self.entry.label)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 15pt; font-weight: 800;")
        lay.addWidget(title)

        self.auto_save = QCheckBox("Auto-save my settings into this profile")
        self.auto_save.setChecked(self.entry.auto_save)
        lay.addWidget(self.auto_save)

        self.auto_load = QCheckBox("Auto-load this profile when selected or at startup")
        self.auto_load.setChecked(self.entry.auto_load)
        lay.addWidget(self.auto_load)

        self.model_label = QLabel(self._model_text())
        self.model_label.setObjectName("hint")
        self.model_label.setWordWrap(True)
        lay.addWidget(self.model_label)

        pick = QPushButton("Set model…")
        pick.setObjectName("ghost")
        pick.clicked.connect(self._pick_model)
        lay.addWidget(pick)

        if self.entry.has_model:
            clear = QPushButton("Remove model")
            clear.setObjectName("ghost")
            clear.clicked.connect(self._clear_model)
            lay.addWidget(clear)

        save = QPushButton("Save profile settings")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        lay.addWidget(save)

        overwrite = QPushButton("Overwrite with my current settings")
        overwrite.setObjectName("ghost")
        overwrite.clicked.connect(self._overwrite)
        lay.addWidget(overwrite)

        close = QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(self.accept)
        lay.addWidget(close)

    def _model_text(self) -> str:
        if self.entry.has_model:
            return f"Model: {self.entry.model_file}"
        return "Model: none (uses whatever model is selected)"

    def _save(self):
        self.entry = self.manager.update_profile_settings(
            self.entry.filename,
            auto_save=self.auto_save.isChecked(),
            auto_load=self.auto_load.isChecked(),
        )
        QMessageBox.information(self, "Profiles", "Profile settings saved.")

    def _overwrite(self):
        self.entry = self.manager.update_profile_settings(
            self.entry.filename,
            auto_save=self.auto_save.isChecked(),
            auto_load=self.auto_load.isChecked(),
        )
        try:
            self.entry = self.manager.update_from_current(self.entry.filename)
            QMessageBox.information(self, "Profiles", "Profile updated with your current settings.")
        except OSError as exc:
            QMessageBox.critical(self, "Profiles", f"Could not update the profile:\n{exc}")

    def _pick_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a model", "", "Models (*.onnx *.engine *.pt);;All files (*.*)")
        if not path:
            return
        try:
            self.entry = self.manager.set_profile_model(self.entry.filename, path)
            self.model_label.setText(self._model_text())
        except OSError as exc:
            QMessageBox.critical(self, "Profiles", f"Could not save the model:\n{exc}")

    def _clear_model(self):
        self.entry = self.manager.clear_profile_model(self.entry.filename)
        self.model_label.setText(self._model_text())
