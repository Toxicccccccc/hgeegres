"""Game config profile picker — 9:16 cards, game art, save/activate/delete."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRectF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPixmap,
    QPainterPath,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QGridLayout, QDialog, QLineEdit, QMessageBox, QCheckBox, QFileDialog,
    QMenu,
)
from game_art import render_game_art, render_cover_only, draw_card_footer, prefetch_all, clear_cache
from game_catalog import GameInfo, GAMES, get_game, search_games
from profile_manager import ProfileEntry, ProfileManager

import theme

CARD_W = 126
CARD_H = 224  # 9:16
CARD_RADIUS = 18
GRID_GAP = 16


class _PortraitButton(QPushButton):
    clicked_payload = pyqtSignal(object)

    def __init__(self, payload=None, parent=None):
        super().__init__(parent)
        self._payload = payload
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setFixedSize(CARD_W, CARD_H)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; margin: 0; }"
            "QPushButton:hover { background: rgba(255,255,255,0.04); }"
        )
        self.clicked.connect(lambda: self.clicked_payload.emit(self._payload))


class AddProfileCard(_PortraitButton):
    def __init__(self, parent=None):
        super().__init__("add", parent)
        self.setObjectName("addProfileCard")
        self.setToolTip("Create a config for a game")

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(QColor("#141414"))
        p.setPen(QPen(QColor("#3a3a3a"), 2, Qt.PenStyle.DashLine))
        p.drawRoundedRect(r, CARD_RADIUS, CARD_RADIUS)
        p.setPen(QPen(QColor(theme.ACCENT_BLUE), 2.5))
        cx, cy = r.center().x(), r.center().y()
        arm = 22
        p.drawLine(cx - arm, cy, cx + arm, cy)
        p.drawLine(cx, cy - arm, cx, cy + arm)
        p.end()


def _rounded_path(rect, radius: float):
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    return path


def _paint_portrait_card(
    p: QPainter,
    outer_rect,
    cover: QPixmap,
    title: str,
    accent: str,
    *,
    border_color: str = "#2f2f2f",
    border_width: int = 1,
    inner_pad: int = 1,
) -> None:
    """Draw cover inside rounded card, then a dedicated footer for the title."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    p.setPen(QPen(QColor(border_color), border_width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(outer_rect, CARD_RADIUS, CARD_RADIUS)

    inner = outer_rect.adjusted(inner_pad, inner_pad, -inner_pad, -inner_pad)
    p.setClipPath(_rounded_path(inner, CARD_RADIUS - 2))
    scaled = cover.scaled(
        inner.size(),
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = inner.x() + (inner.width() - scaled.width()) // 2
    y = inner.y() + (inner.height() - scaled.height()) // 2
    p.drawPixmap(x, y, scaled)
    p.setClipping(False)

    draw_card_footer(p, inner, title, accent, CARD_RADIUS - 2)


class ProfileCard(_PortraitButton):
    edit_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)

    def __init__(self, entry: ProfileEntry, parent=None):
        super().__init__(entry, parent)
        self.entry = entry
        game = get_game(entry.game_id)
        self._game = game or GameInfo(
            entry.game_id, entry.display_name, "#27272a", "#52525b", theme.ACCENT_BLUE
        )
        self._cover = render_cover_only(self._game, CARD_W - 4, CARD_H - 4)
        self.setToolTip(f"{entry.filename}\nClick to load · Right-click to edit or delete")
        if entry.active:
            self.setObjectName("activeProfileCard")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        edit_act = menu.addAction("Edit…")
        delete_act = menu.addAction("Delete…")
        chosen = menu.exec(event.globalPos())
        if chosen == edit_act:
            self.edit_requested.emit(self.entry)
        elif chosen == delete_act:
            self.delete_requested.emit(self.entry)

    def paintEvent(self, _event):
        p = QPainter(self)
        r = self.rect().adjusted(1, 1, -1, -1)
        border = theme.ACCENT_SELECT if self.entry.active else "#2f2f2f"
        bw = 3 if self.entry.active else 1
        pad = 3 if self.entry.active else 1

        _paint_portrait_card(
            p, r, self._cover, self.entry.label, self._game.accent,
            border_color=border, border_width=bw, inner_pad=pad,
        )

        if self.entry.active:
            inner = r.adjusted(pad, pad, -pad, -pad)
            p.setBrush(QColor(theme.GOOD))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(inner.right() - 18, inner.top() + 8, 10, 10)
        if self.entry.has_model:
            inner = r.adjusted(pad, pad, -pad, -pad)
            p.setBrush(QColor(theme.ACCENT_BLUE))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(inner.left() + 8, inner.top() + 8, 10, 10)
        p.end()


class GamePortraitCard(_PortraitButton):
    """9:16 game card with cover art painted directly."""

    def __init__(self, game: GameInfo, parent=None):
        super().__init__(game, parent)
        self.game = game
        self._cover = render_cover_only(game, CARD_W - 4, CARD_H - 4)
        self.setToolTip(game.name)

    def paintEvent(self, _event):
        p = QPainter(self)
        r = self.rect().adjusted(1, 1, -1, -1)
        _paint_portrait_card(p, r, self._cover, self.game.name, self.game.accent, border_color="#3a3a3a")
        p.end()


class GamePickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose a game")
        self.setModal(True)
        self.resize(760, 640)
        self.selected: GameInfo | None = None
        self._build()
        # Build UI first, then load covers and repaint cards on the main thread.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._load_covers)

    def _load_covers(self):
        prefetch_all()
        clear_cache()
        self._refresh_grid(force=True)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("Pick a game for this config")
        title.setStyleSheet("font-size: 15pt; font-weight: 800;")
        root.addWidget(title)

        hint = QLabel("Each profile stores a full config.json preset for that title.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games…")
        self.search.textChanged.connect(self._refresh_grid)
        root.addWidget(self.search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setHorizontalSpacing(GRID_GAP)
        self.grid.setVerticalSpacing(GRID_GAP)
        scroll.setWidget(self.grid_host)
        root.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        root.addLayout(row)

        self._refresh_grid()

    def _pick(self, game: GameInfo):
        self.selected = game
        self.accept()

    def _refresh_grid(self, force: bool = False):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        games = search_games(self.search.text())
        cols = 5
        for i, game in enumerate(games):
            card = GamePortraitCard(game)
            card.clicked_payload.connect(self._pick)
            self.grid.addWidget(card, i // cols, i % cols)


class ProfileActionDialog(QDialog):
    SAVE_CURRENT = "save"
    CREATE_NEW = "new"

    def __init__(self, game: GameInfo, parent=None):
        super().__init__(parent)
        self.game = game
        self.choice: str | None = None
        self.setWindowTitle(game.name)
        self.setModal(True)
        self.resize(420, 520)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 22)
        lay.setSpacing(14)

        art = QLabel()
        art.setPixmap(render_game_art(self.game, 180, 320))
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(art)

        title = QLabel(self.game.name)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16pt; font-weight: 800;")
        lay.addWidget(title)

        sub = QLabel("How should this profile be created?")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setObjectName("hint")
        lay.addWidget(sub)

        save_btn = QPushButton("Save current settings")
        save_btn.setObjectName("primary")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(lambda: self._choose(self.SAVE_CURRENT))
        lay.addWidget(save_btn)

        new_btn = QPushButton("Start with default settings")
        new_btn.setObjectName("ghost")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(lambda: self._choose(self.CREATE_NEW))
        lay.addWidget(new_btn)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel)

    def _choose(self, choice: str):
        self.choice = choice
        self.accept()


class ProfileEditDialog(QDialog):
    """Edit profile settings, model, and toggles."""

    def __init__(self, manager: ProfileManager, entry: ProfileEntry, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.entry = entry
        game = get_game(entry.game_id)
        self.game = game or GameInfo(
            entry.game_id, entry.display_name, "#27272a", "#52525b", theme.ACCENT_BLUE
        )
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

        meta = QLabel(self.entry.filename)
        meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meta.setObjectName("hint")
        lay.addWidget(meta)

        self.auto_save_chk = QCheckBox("Auto-save to this profile when I click Save")
        self.auto_save_chk.setChecked(self.entry.auto_save)
        lay.addWidget(self.auto_save_chk)

        self.auto_load_chk = QCheckBox("Auto-load when selected or on startup")
        self.auto_load_chk.setChecked(self.entry.auto_load)
        self.auto_load_chk.setToolTip(
            "Left-click loads this profile. When enabled, it also auto-loads on app startup "
            "if this profile is active."
        )
        lay.addWidget(self.auto_load_chk)

        model_row = QHBoxLayout()
        self.model_lbl = QLabel(self._model_label_text())
        self.model_lbl.setObjectName("hint")
        self.model_lbl.setWordWrap(True)
        model_row.addWidget(self.model_lbl, 1)

        set_model = QPushButton("Set model…")
        set_model.setObjectName("ghost")
        set_model.clicked.connect(self._pick_model)
        model_row.addWidget(set_model)

        if self.entry.has_model:
            clr = QPushButton("Remove")
            clr.setObjectName("ghost")
            clr.clicked.connect(self._clear_model)
            model_row.addWidget(clr)
        lay.addLayout(model_row)

        save_btn = QPushButton("Save profile settings")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_settings)
        lay.addWidget(save_btn)

        upd = QPushButton("Overwrite profile with current settings")
        upd.setObjectName("ghost")
        upd.clicked.connect(self._overwrite)
        lay.addWidget(upd)

        close = QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(self.accept)
        lay.addWidget(close)

    def _model_label_text(self) -> str:
        if self.entry.has_model:
            return f"Model: ui/models/{self.entry.model_file} → best.onnx when loaded"
        return "Model: none (won't change best.onnx)"

    def _persist_toggles(self):
        self.entry = self.manager.update_profile_settings(
            self.entry.filename,
            auto_save=self.auto_save_chk.isChecked(),
            auto_load=self.auto_load_chk.isChecked(),
        )

    def _save_settings(self):
        self._persist_toggles()
        QMessageBox.information(self, "Saved", "Profile settings updated.")

    def _overwrite(self):
        self._persist_toggles()
        try:
            self.entry = self.manager.update_from_current(self.entry.filename, deploy_live=False)
            QMessageBox.information(self, "Saved", "Profile updated with your current settings.")
        except OSError as e:
            QMessageBox.critical(self, "Inchro", f"Could not update profile:\n{e}")

    def _pick_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ONNX model", "", "ONNX models (*.onnx);;All files (*.*)",
        )
        if not path:
            return
        try:
            self._persist_toggles()
            self.entry = self.manager.set_profile_model(self.entry.filename, path)
            self.model_lbl.setText(self._model_label_text())
        except OSError as e:
            QMessageBox.critical(self, "Inchro", f"Could not save model:\n{e}")

    def _clear_model(self):
        if QMessageBox.question(
            self, "Remove model", f"Remove {self.entry.model_file}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.entry = self.manager.clear_profile_model(self.entry.filename)
        self.model_lbl.setText(self._model_label_text())


class ConfigProfilesPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, manager: ProfileManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._last_cols = 0
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 92, 24)
        outer.setSpacing(10)

        title = QLabel("Configs")
        title.setStyleSheet("font-size: 16pt; font-weight: 800;")
        outer.addWidget(title)

        status_row = QHBoxLayout()
        self.active_lbl = QLabel("")
        self.active_lbl.setStyleSheet(f"color: {theme.GOOD}; font-weight: 700;")
        status_row.addWidget(self.active_lbl, 1)

        self.unload_btn = QPushButton("Unload")
        self.unload_btn.setObjectName("ghost")
        self.unload_btn.setToolTip("Restore config.json and best.onnx from before the last profile load")
        self.unload_btn.clicked.connect(self._unload_profile)
        status_row.addWidget(self.unload_btn)
        outer.addLayout(status_row)

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

        QTimer.singleShot(0, self._prefetch_covers)

    def _update_status(self):
        active = self.manager.active_filename()
        if active:
            self.active_lbl.setText(f"Active: {active}")
        else:
            self.active_lbl.setText("No profile loaded")
        self.unload_btn.setEnabled(self.manager.can_unload())

    def _unload_profile(self):
        if not self.manager.can_unload():
            QMessageBox.information(self, "Unload", "Nothing to unload yet.\nLoad a profile first.")
            return
        try:
            if self.manager.unload():
                self.changed.emit()
                self.refresh(force=True)
        except OSError as e:
            QMessageBox.critical(self, "Inchro", f"Could not unload:\n{e}")

    def _prefetch_covers(self):
        prefetch_all()
        clear_cache()
        self.refresh(force=True)

    def refresh(self, *, force: bool = False):
        cols = max(3, (max(self.width(), 640) - 140) // (CARD_W + GRID_GAP))
        if not force and cols == self._last_cols and self.grid.count() > 0:
            self._update_status()
            return
        self._last_cols = cols

        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        profiles = self.manager.list_profiles()
        self._update_status()

        add = AddProfileCard()
        add.clicked_payload.connect(lambda _: self._on_add())
        self.grid.addWidget(add, 0, 0)

        for i, entry in enumerate(profiles):
            card = ProfileCard(entry)
            card.clicked_payload.connect(self._on_profile_load)
            card.edit_requested.connect(self._on_profile_edit)
            card.delete_requested.connect(self._on_profile_delete)
            self.grid.addWidget(card, (i + 1) // cols, (i + 1) % cols)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def _on_add(self):
        picker = GamePickerDialog(self)
        if picker.exec() != QDialog.DialogCode.Accepted or not picker.selected:
            return
        game = picker.selected
        dlg = ProfileActionDialog(game, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
            return
        try:
            if dlg.choice == ProfileActionDialog.SAVE_CURRENT:
                self.manager.save_current_as(game.id, game.name)
            else:
                self.manager.create_fresh(game.id, game.name)
        except OSError as e:
            QMessageBox.critical(self, "Inchro", f"Could not save profile:\n{e}")
            return
        self.changed.emit()
        self.refresh(force=True)

    def _on_profile_load(self, entry: ProfileEntry):
        try:
            self.manager.activate(entry.filename, force=True)
        except OSError as e:
            QMessageBox.critical(self, "Inchro", f"Could not load profile:\n{e}")
            return
        self.changed.emit()
        self.refresh(force=True)

    def _on_profile_edit(self, entry: ProfileEntry):
        dlg = ProfileEditDialog(self.manager, entry, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.changed.emit()
            self.refresh(force=True)

    def _on_profile_delete(self, entry: ProfileEntry):
        if not self._confirm_delete(entry):
            return
        try:
            self.manager.delete(entry.filename)
        except OSError as e:
            QMessageBox.critical(self, "Inchro", f"Could not delete profile:\n{e}")
            return
        self.changed.emit()
        self.refresh(force=True)

    def _confirm_delete(self, entry: ProfileEntry) -> bool:
        msg = f"Delete {entry.label} ({entry.filename})?"
        if entry.active:
            msg += (
                "\n\nThis is your active profile. Inchro will switch to another saved profile, "
                "or reset to defaults if none remain."
            )
        return QMessageBox.question(
            self, "Delete profile", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes
