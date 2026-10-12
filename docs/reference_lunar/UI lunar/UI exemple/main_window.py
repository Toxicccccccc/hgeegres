"""Inchro main window.

PyQt6 front-end patterned on Lunar V2: sidebar navigation, schema-driven
config editors, Backend console, optional Python FOV overlay, and login
prompting when the C++ backend signals auth expiry.
"""

import os
import shutil

from PyQt6.QtCore import (
    Qt, QTimer, QSize, QUrl, QPointF, QPropertyAnimation,
    QParallelAnimationGroup, QEasingCurve, QFileSystemWatcher,
)
from PyQt6.QtGui import (
    QIcon, QColor, QDesktopServices, QFontDatabase, QFont, QPixmap, QPainter,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QScrollArea, QPlainTextEdit, QLineEdit, QFileDialog,
    QSizePolicy, QGraphicsDropShadowEffect, QCheckBox, QMessageBox,
)

import theme
import nav_icons
from config_schema import SCHEMA
from config_manager import ConfigManager
from app_settings import AppSettings
from widgets import FieldRow, Card
from backend import Backend, EXIT_LOGGED_OUT, EXIT_LOGIN_FAILED
from overlay import Overlay
from login_dialog import LoginDialog
from config_profiles_ui import ConfigProfilesPage
from profile_manager import ProfileManager
from busy_overlay import BusyOverlay


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Inchro")
        if os.path.isfile(theme.WINDOW_ICON):
            self.setWindowIcon(QIcon(theme.WINDOW_ICON))
        self.setMinimumSize(940, 600)
        self.setStyleSheet(theme.STYLE)

        self._load_font()

        self.settings = AppSettings()
        self.config = ConfigManager(self.settings.get("config_path"))
        self.profiles = ProfileManager(
            configs_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs"),
            models_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"),
            live_config_path=self._live_config_path,
            live_model_path=self._live_model_path,
            gather_values=self._gather,
            save_live=lambda values: self.config.save(values),
            reload_ui=self._load_into_ui,
        )
        self.backend = Backend(self)
        self.overlay = Overlay()

        self.rows: dict[str, FieldRow] = {}
        self._tab_names: list[str] = []
        self.nav_buttons: list[QPushButton] = []
        self.floating_buttons: list[QPushButton] = []
        self._awaiting_login = False
        self._login_prompt_pending = False
        self._status_override: str | None = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._do_save)

        self._config_watcher = QFileSystemWatcher(self)
        self._config_watcher.fileChanged.connect(self._on_config_file_changed)
        self._config_reload_timer = QTimer(self)
        self._config_reload_timer.setSingleShot(True)
        self._config_reload_timer.setInterval(250)
        self._config_reload_timer.timeout.connect(self._reload_config_from_disk)
        self._config_reload_blocked = False

        self._build()
        self.busy_overlay = BusyOverlay(self.stack)
        self._init_floating_buttons()
        self._load_into_ui()
        self._update_title_with_config()
        self._watch_config_file()
        self.profiles.maybe_load_active_on_startup()

        self.backend.output.connect(self._append_console)
        self.backend.state_changed.connect(self._on_backend_state)
        self.backend.auth_event.connect(self._on_auth_event)
        self.backend.finished_with_code.connect(self._on_backend_finished)
        self.backend.busy_changed.connect(self._on_busy_changed)
        self.backend.start_completed.connect(self._on_start_completed)

        self._select_tab(0)
        QTimer.singleShot(0, self._log_loaded_config_summary)

    def _load_font(self):
        if os.path.isfile(theme.FONT_PATH):
            fid = QFontDatabase.addApplicationFont(theme.FONT_PATH)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
            if fams:
                from PyQt6.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    f = QFont(fams[0])
                    f.setPointSizeF(10.5)
                    app.setFont(f)

    TAB_ORDER = [
        "Aim", "Detection", "Configs", "Triggerbot", "Capture", "Input & Device",
        "Overlay", "Discord Overlay", "Debug", "Backend",
    ]

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        for tab in self.TAB_ORDER:
            self._tab_names.append(tab)
            if tab == "Configs":
                self.profiles_page = ConfigProfilesPage(self.profiles)
                self.profiles_page.changed.connect(self._on_profile_changed)
                self.stack.addWidget(self.profiles_page)
            elif tab == "Overlay":
                self.stack.addWidget(self._build_overlay_page())
            elif tab == "Backend":
                self.stack.addWidget(self._build_backend_page())
            else:
                self.stack.addWidget(self._build_tab_page(tab))

        root.addWidget(self.stack, 1)

    SIDEBAR_W = 212
    SIDEBAR_W_COLLAPSED = 64

    def _build_sidebar(self) -> QFrame:
        self._collapsed = False
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(self.SIDEBAR_W)
        bar.setStyleSheet(theme.SIDEBAR)
        self.sidebar = bar

        lay = QVBoxLayout(bar)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.setContentsMargins(10, 12, 10, 12)
        lay.setSpacing(3)

        lay.addLayout(self._build_header())
        lay.addSpacing(6)

        for i, name in enumerate(self.TAB_ORDER):
            btn = self._make_nav_item(name, nav_icons.TAB_ICON.get(name, "sliders"))
            btn.clicked.connect(lambda _=False, idx=i: self._select_tab(idx))
            self.nav_buttons.append(btn)
            lay.addWidget(btn)

        lay.addStretch()

        divider = QFrame()
        divider.setObjectName("navDivider")
        lay.addWidget(divider)
        lay.addSpacing(6)

        self.discord_item = self._make_nav_item("Discord", "discord")
        self.discord_item.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://discord.gg/9ZaH7VK8kY"))
        )
        lay.addWidget(self.discord_item)
        return bar

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._header_row = row

        row.addStretch(1)
        self.collapse_btn = QPushButton()
        self.collapse_btn.setObjectName("collapseBtn")
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.setFixedSize(34, 34)
        self.collapse_btn.setIconSize(QSize(18, 18))
        self.collapse_btn.setIcon(nav_icons.make_icon("collapse", theme.TEXT_DIM, 18))
        self.collapse_btn.setToolTip("Collapse sidebar")
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        row.addWidget(self.collapse_btn)
        row.addStretch(0)
        return row

    @staticmethod
    def _nav_text(name: str) -> str:
        return "  " + name.replace("&", "&&")

    def _make_nav_item(self, name: str, icon_key: str) -> QPushButton:
        btn = QPushButton(self._nav_text(name))
        btn.setObjectName("navItem")
        btn.setProperty("navName", name)
        btn.setProperty("iconKey", icon_key)
        btn.setToolTip(name)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIconSize(QSize(20, 20))
        btn.setIcon(nav_icons.make_icon(icon_key, theme.TEXT_DIM, 20))
        btn.setMinimumHeight(38)
        return btn

    def _apply_nav_collapsed(self, collapsed: bool):
        for btn in self.nav_buttons + [self.discord_item]:
            name = btn.property("navName")
            btn.setText("" if collapsed else self._nav_text(name))
            btn.setProperty("collapsed", collapsed)
            self._repolish(btn)

    def _toggle_sidebar(self):
        self._collapsed = not self._collapsed
        target = self.SIDEBAR_W_COLLAPSED if self._collapsed else self.SIDEBAR_W
        start = self.sidebar.width()

        self.collapse_btn.setIcon(
            nav_icons.make_icon("expand" if self._collapsed else "collapse",
                                theme.TEXT_DIM, 18)
        )
        self.collapse_btn.setToolTip(
            "Expand sidebar" if self._collapsed else "Collapse sidebar"
        )
        self._header_row.setStretch(2, 1 if self._collapsed else 0)

        if self._collapsed:
            self._apply_nav_collapsed(True)

        grp = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self.sidebar, prop, self)
            anim.setDuration(190)
            anim.setStartValue(start)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            grp.addAnimation(anim)
        if not self._collapsed:
            grp.finished.connect(lambda: self._apply_nav_collapsed(False))
        grp.start()
        self._sidebar_anim = grp

    def _build_tab_page(self, tab: str) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL)

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 92, 24)
        lay.setSpacing(12)

        title = QLabel(tab)
        title.setObjectName("tabHeader")
        title.setStyleSheet("font-size: 16pt; font-weight: 800;")
        lay.addWidget(title)

        for card_def in SCHEMA[tab]:
            card = Card(card_def["title"])
            for field in card_def["fields"]:
                row = FieldRow(field)
                row.changed.connect(self._on_field_changed)
                self.rows[field["key"]] = row
                card.add_row(row)
            lay.addWidget(card)

        lay.addStretch()
        scroll.setWidget(page)
        return scroll

    def _build_overlay_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 92, 24)
        lay.setSpacing(12)

        title = QLabel("Overlay")
        title.setStyleSheet("font-size: 16pt; font-weight: 800;")
        lay.addWidget(title)

        ov = Card("Python Overlay")
        self.overlay_btn = QPushButton("Enable Overlay")
        self.overlay_btn.setObjectName("ghost")
        self.overlay_btn.setCheckable(True)
        self.overlay_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay_btn.toggled.connect(self._toggle_overlay)
        ov.add_row(self.overlay_btn)
        note = QLabel(
            "Transparent FOV + crosshair overlay. Detection boxes stream live from "
            "the running backend (Inchro.exe)."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        ov.add_row(note)
        lay.addWidget(ov)

        disp = Card("Display")
        self._overlay_show_checks = {}
        for key, label, default, kwarg in (
            ("overlay_show_fov", "Show FOV", True, "show_fov"),
            ("overlay_show_crosshair", "Show Crosshair", True, "show_crosshair"),
            ("overlay_show_detections", "Show Detections", True, "show_detections"),
        ):
            val = bool(self.settings.get(key, default))
            self.overlay.set_options(**{kwarg: val})
            chk = QCheckBox(label)
            chk.setChecked(val)
            chk.toggled.connect(lambda on, k=key: self._on_overlay_display_changed(k, on))
            self._overlay_show_checks[key] = chk
            disp.add_row(chk)
        lay.addWidget(disp)

        lay.addStretch()
        scroll.setWidget(page)
        return scroll

    def _on_overlay_display_changed(self, key: str, on: bool):
        self.settings.set(key, on)
        self.settings.save()
        kwarg = {
            "overlay_show_fov": "show_fov",
            "overlay_show_crosshair": "show_crosshair",
            "overlay_show_detections": "show_detections",
        }[key]
        self.overlay.set_options(**{kwarg: on})

    def _build_backend_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 92, 24)
        lay.setSpacing(12)

        title = QLabel("Backend")
        title.setStyleSheet("font-size: 16pt; font-weight: 800;")
        lay.addWidget(title)

        run = Card("Run Control")
        row = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.setStyleSheet(f"background: {theme.TEXT_DIM}; border-radius: 5px;")
        row.addWidget(self.status_dot)
        row.addSpacing(6)
        self.status_lbl = QLabel("Stopped")
        self.status_lbl.setObjectName("statusStopped")
        row.addWidget(self.status_lbl)
        row.addStretch()
        self.login_btn = QPushButton("Login…")
        self.login_btn.setObjectName("ghost")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.clicked.connect(lambda: self._prompt_login_and_start(
            "Sign in, then start the backend."
        ))
        row.addWidget(self.login_btn)
        self.run_btn = QPushButton("Start")
        self.run_btn.setObjectName("primary")
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_btn.clicked.connect(self._toggle_backend)
        row.addWidget(self.run_btn)
        rc = QWidget()
        rc.setLayout(row)
        run.add_row(rc)
        lay.addWidget(run)

        paths = Card("Paths")
        self.exe_edit = self._path_row(paths, "Inchro.exe", self.settings.get("exe_path"),
                                       self._pick_exe)
        self.cfg_edit = self._path_row(paths, "config.json", self.settings.get("config_path"),
                                       self._pick_cfg)
        self.cfg_edit.editingFinished.connect(self._on_config_path_edited)
        lay.addWidget(paths)

        con = Card("Backend Console")
        self.console = QPlainTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(240)
        con.add_row(self.console)
        lay.addWidget(con)

        lay.addStretch()
        scroll.setWidget(page)
        return scroll

    def _path_row(self, card: Card, label: str, value: str, on_browse) -> QLineEdit:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 4, 0, 4)
        lbl = QLabel(label)
        lbl.setFixedWidth(90)
        edit = QLineEdit(value or "")
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        browse = QPushButton("Browse")
        browse.setObjectName("ghost")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(lambda: on_browse(edit))
        h.addWidget(lbl)
        h.addWidget(edit, 1)
        h.addWidget(browse)
        card.add_row(wrap)
        return edit

    def _init_floating_buttons(self):
        self._fb_size = 52
        self._fb_gap = 10
        self._fb_margin_r = 24
        self._fb_margin_b = 28

        specs = [
            (None, "play", "Start / Stop backend", self._toggle_backend),
            ("config.png", None, "Edit config.json", self._open_config_file),
            ("refresh.png", None, "Refresh style", self._refresh_style),
            ("save.png", None, "Save settings", self._do_save),
        ]
        for icon_file, shape, tip, cb in specs:
            btn = QPushButton(self)
            btn.setFixedSize(self._fb_size, self._fb_size)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(theme.FLOATING)
            btn.setIconSize(QSize(20, 20))
            path = theme.icon(icon_file) if icon_file else ""
            if path and os.path.isfile(path):
                btn.setIcon(QIcon(path))
            elif shape:
                btn.setIcon(self._shape_icon(shape, theme.GOOD))
            shadow = QGraphicsDropShadowEffect(btn)
            shadow.setBlurRadius(20)
            shadow.setColor(QColor(0, 0, 0, 180))
            shadow.setOffset(0, 2)
            btn.setGraphicsEffect(shadow)
            btn.clicked.connect(cb)
            btn.show()
            self.floating_buttons.append(btn)

        self.run_fab = self.floating_buttons[0]
        self._style_run_fab(False)
        QTimer.singleShot(60, self._position_floating_buttons)

    @staticmethod
    def _shape_icon(shape: str, color: str) -> QIcon:
        pm = QPixmap(40, 40)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        if shape == "play":
            p.drawPolygon(QPolygonF([QPointF(14, 11), QPointF(14, 29), QPointF(30, 20)]))
        else:
            p.drawRoundedRect(12, 12, 16, 16, 3, 3)
        p.end()
        return QIcon(pm)

    def _style_run_fab(self, running: bool):
        color = theme.BAD if running else theme.GOOD
        self.run_fab.setIcon(self._shape_icon("stop" if running else "play", color))

    def _position_floating_buttons(self):
        n = len(self.floating_buttons)
        total = n * self._fb_size + (n - 1) * self._fb_gap
        start_y = self.height() - total - self._fb_margin_b
        x = self.width() - self._fb_size - self._fb_margin_r
        for i, btn in enumerate(self.floating_buttons):
            btn.move(x, start_y + i * (self._fb_size + self._fb_gap))
            btn.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.floating_buttons:
            self._position_floating_buttons()

    def showEvent(self, e):
        super().showEvent(e)
        self._position_floating_buttons()

    def _default_config_path(self) -> str:
        exe = self.settings.get("exe_path", "").strip()
        if exe:
            return os.path.join(os.path.dirname(os.path.abspath(exe)), "config.json")
        return self.config.path

    def _resolved_config_path(self) -> str:
        if hasattr(self, "cfg_edit"):
            custom = self.cfg_edit.text().strip()
            if custom:
                return custom
        custom = self.settings.get("config_path", "").strip()
        if custom:
            return custom
        return self._default_config_path()

    def _live_config_path(self) -> str:
        return self._resolved_config_path()

    def _live_model_path(self) -> str:
        cfg = self._live_config_path()
        folder = os.path.dirname(os.path.abspath(cfg)) if cfg else ""
        return os.path.join(folder, "best.onnx") if folder else "best.onnx"

    def _apply_config_path(self, path: str, *, reload: bool = True) -> None:
        path = path.strip()
        if not path:
            return
        self.config.path = path
        self.settings.set("config_path", path)
        self.settings.save()
        if hasattr(self, "cfg_edit") and self.cfg_edit.text().strip() != path:
            self.cfg_edit.blockSignals(True)
            self.cfg_edit.setText(path)
            self.cfg_edit.blockSignals(False)
        self._watch_config_file()
        if reload:
            self._load_into_ui()

    def _watch_config_file(self) -> None:
        path = self.config.path
        watched = self._config_watcher.files()
        if watched:
            self._config_watcher.removePaths(watched)
        if path and os.path.isfile(path):
            self._config_watcher.addPath(path)

    def _on_config_file_changed(self, _path: str) -> None:
        if self._config_reload_blocked:
            return
        self._config_reload_timer.start()

    def _reload_config_from_disk(self) -> None:
        if self._config_reload_blocked:
            return
        self._load_into_ui()
        self._watch_config_file()

    def _exe_config_path(self) -> str | None:
        exe = self.settings.get("exe_path", "").strip()
        if not exe:
            return None
        return os.path.join(os.path.dirname(os.path.abspath(exe)), "config.json")

    def _mirror_config_to_exe(self) -> None:
        """Keep Inchro.exe's folder config.json in sync when using a different UI path."""
        exe_cfg = self._exe_config_path()
        if not exe_cfg:
            return
        if os.path.normcase(exe_cfg) == os.path.normcase(self.config.path):
            return
        if not os.path.isfile(self.config.path):
            return
        os.makedirs(os.path.dirname(os.path.abspath(exe_cfg)), exist_ok=True)
        shutil.copy2(self.config.path, exe_cfg)
        if hasattr(self, "console"):
            self._append_console(f"[config] mirrored to {exe_cfg}\n")

    def _on_config_path_edited(self) -> None:
        path = self.cfg_edit.text().strip()
        if not path or path == self.config.path:
            return
        self._apply_config_path(path, reload=True)

    def _on_profile_changed(self):
        live = self._live_config_path()
        if self.config.path != live:
            self._apply_config_path(live, reload=True)
        else:
            self._load_into_ui()
        self._watch_config_file()
        if hasattr(self, "profiles_page"):
            self.profiles_page.refresh(force=True)
        if hasattr(self, "console"):
            entry = self.profiles.get_active_profile()
            model_note = f"  model={entry.model_file}" if entry and entry.has_model else ""
            self._append_console(
                f"[config] active profile: {self.profiles.active_filename() or 'none'}{model_note}\n"
            )

    def _select_tab(self, idx: int):
        self.stack.setCurrentIndex(idx)
        if self._tab_names[idx] == "Configs" and hasattr(self, "profiles_page"):
            self.profiles_page.refresh(force=True)
        for i, btn in enumerate(self.nav_buttons):
            selected = i == idx
            btn.setProperty("selected", selected)
            color = "#ffffff" if selected else theme.TEXT_DIM
            btn.setIcon(nav_icons.make_icon(btn.property("iconKey"), color, 20))
            self._repolish(btn)

    def _on_field_changed(self):
        if "fovSize" in self.rows:
            self.overlay.set_options(fov_size=self.rows["fovSize"].value())
        # Choice rows emit on any change; re-apply conditional visibility.
        self._update_conditional_field_visibility()
        if self.settings.get("auto_save", True):
            self._save_timer.start()

    def _update_conditional_field_visibility(self):
        """Show fields gated by visible_for / visible_when (mouseMethod, captureMethod, …)."""
        for key, row in self.rows.items():
            allowed = row.field.get("visible_for")
            if allowed is None:
                continue
            driver_key = row.field.get("visible_when") or "mouseMethod"
            driver = ""
            if driver_key in self.rows:
                val = self.rows[driver_key].value()
                driver = "True" if val is True else ("False" if val is False else str(val))
            row.setVisible(driver in allowed)

    def _load_into_ui(self):
        data = self.config.load()
        for key, row in self.rows.items():
            if key in data:
                row.set_value(data[key])
        self.overlay.set_options(fov_size=data.get("fovSize", 640))
        self._update_conditional_field_visibility()
        self._update_title_with_config()

    def _update_title_with_config(self):
        n = len(self.rows)
        self.setWindowTitle(f"Inchro Config Editor ({n} settings)")

    def _log_loaded_config_summary(self):
        if not hasattr(self, "console"):
            return
        path = self.config.path
        exists = os.path.isfile(path) if path else False
        data = self.config.load()
        self._append_console(
            f"[config] {path}\n"
            f"[config] file={'found' if exists else 'MISSING'}  "
            f"ui_fields={len(self.rows)}  file_keys={len(data)}\n"
            f"[config] baseSpeed={data.get('baseSpeed')}  "
            f"predictionFadeinRange={data.get('predictionFadeinRange')}  "
            f"comport={data.get('comport')}  "
            f"overlaySmoothSpeed={data.get('overlaySmoothSpeed')}\n"
        )

    def _gather(self) -> dict:
        return {key: row.value() for key, row in self.rows.items()}

    def _do_save(self):
        self._sync_paths()
        try:
            values = self._gather()
            self._config_reload_blocked = True
            self.config.save(values)
            self._mirror_config_to_exe()
            if self.profiles.save_active_profile_if_enabled():
                active = self.profiles.active_filename()
                if hasattr(self, "console"):
                    self._append_console(f"[profile] synced settings to {active}\n")
            self._config_reload_blocked = False
            self._load_into_ui()
            self._watch_config_file()
            self._flash_status_saved()
        except OSError as e:
            self._config_reload_blocked = False
            self._append_console(f"\n[save error] {e}\n")

    def _sync_paths(self):
        if hasattr(self, "exe_edit"):
            self.settings.set("exe_path", self.exe_edit.text().strip())
        if hasattr(self, "cfg_edit"):
            new_cfg = self.cfg_edit.text().strip()
            if new_cfg and new_cfg != self.config.path:
                self._apply_config_path(new_cfg, reload=False)
        self.settings.save()

    def _flash_status_saved(self):
        if not self.backend.is_running() and not self._status_override:
            self.status_lbl.setText("Saved")
            self.status_lbl.setObjectName("statusRunning")
            self.status_dot.setStyleSheet(f"background: {theme.GOOD}; border-radius: 5px;")
            self._repolish(self.status_lbl)
            QTimer.singleShot(900, lambda: self._on_backend_state(self.backend.is_running()))

    def _toggle_backend(self):
        if self.backend.is_busy():
            return
        if self.backend.is_running():
            self.backend.stop()
            return
        self._start_backend()

    def _on_busy_changed(self, busy: bool, message: str):
        if busy:
            self.busy_overlay.show_busy(message)
        else:
            self.busy_overlay.hide_busy()
        self._set_run_controls_enabled(not busy)

    def _set_run_controls_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled)
        self.login_btn.setEnabled(enabled)
        if hasattr(self, "run_fab"):
            self.run_fab.setEnabled(enabled)

    def _on_start_completed(self, ok: bool, msg: str):
        self._append_console(msg + "\n")
        if not ok:
            self._set_status("Start failed", bad=True)

    @staticmethod
    def _has_local_session(exe_path: str) -> bool:
        if not exe_path:
            return False
        folder = os.path.dirname(os.path.abspath(exe_path))
        return (
            os.path.isfile(os.path.join(folder, "jwt_cache.bin"))
            and os.path.isfile(os.path.join(folder, "user_cache.bin"))
        )

    def _schedule_login_prompt(self, message: str):
        if self._awaiting_login or self._login_prompt_pending:
            return
        if self.backend.is_busy():
            QTimer.singleShot(50, lambda: self._schedule_login_prompt(message))
            return
        self._login_prompt_pending = True
        QTimer.singleShot(0, lambda: self._run_login_prompt(message))

    def _run_login_prompt(self, message: str):
        self._login_prompt_pending = False
        self.busy_overlay.hide_busy()
        self._set_run_controls_enabled(True)
        self._prompt_login_and_start(message)

    def _start_backend(self):
        self._do_save()
        self._status_override = None
        exe = self.settings.get("exe_path")
        if not self._has_local_session(exe):
            self._schedule_login_prompt("Sign in to start the backend.")
            return
        self.backend.start_async(exe)

    def _prompt_login_and_start(self, message: str) -> bool:
        if self._awaiting_login:
            return False
        self._awaiting_login = True
        try:
            cached = self.settings.get("cached_username", "") or ""
            dlg = LoginDialog(self, username=cached, message=message, app_name="Inchro")
            if dlg.exec() != LoginDialog.DialogCode.Accepted:
                self._set_status("Login cancelled", bad=True)
                return False
            user, password = dlg.credentials()
            if not user or not password:
                QMessageBox.warning(self, "Inchro", "Username and password are required.")
                return False
            self.settings.set("cached_username", user)
            self.settings.save()
            exe = self.settings.get("exe_path")
            try:
                self.backend.write_auth_boot(exe, user, password)
            except OSError as e:
                self._append_console(f"\n[auth] failed to write ui_auth.json: {e}\n")
                return False
            self._append_console("[auth] Credentials queued for backend login.\n")
            self._start_backend_after_login()
            return True
        finally:
            self._awaiting_login = False

    def _start_backend_after_login(self):
        self._status_override = None
        self.backend.start_async(self.settings.get("exe_path"))

    def _on_auth_event(self, event: str, detail: str):
        if event == "logged_in":
            self._status_override = None
            name = detail or "user"
            self._append_console(f"[auth] Logged in as {name}\n")
            if self.backend.is_running():
                self._set_status(f"Running ({name})", bad=False)
        elif event == "need_login":
            self._set_status("Login required", bad=True)
            self._append_console("[auth] Backend needs login.\n")
            self._schedule_login_prompt("Sign in to continue.")
        elif event == "login_failed":
            self._set_status("Login failed", bad=True)
            self._append_console(f"[auth] Login failed: {detail}\n")
            self._schedule_login_prompt(
                detail or "Login failed. Check your credentials and try again."
            )
        elif event == "logout":
            self._set_status("Logged out", bad=True)
            self._append_console("[auth] Session expired — please log in again.\n")
            self._schedule_login_prompt(
                "Your session expired. Enter your Inchro credentials."
            )

    def _on_backend_finished(self, code: int):
        if self.backend.was_user_stopped():
            self._status_override = None
            return
        if code == EXIT_LOGGED_OUT:
            self._set_status("Logged out", bad=True)
            self._schedule_login_prompt(
                "You were logged out or need to sign in. Enter your Inchro credentials."
            )
        elif code == EXIT_LOGIN_FAILED:
            self._set_status("Login failed", bad=True)
            self._schedule_login_prompt(
                "Login failed. Check your credentials and try again."
            )

    def _set_status(self, text: str, *, bad: bool):
        self._status_override = text
        self.status_lbl.setText(text)
        self.status_lbl.setObjectName("statusStopped" if bad else "statusRunning")
        color = theme.BAD if bad else theme.GOOD
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
        self._repolish(self.status_lbl)

    def _on_backend_state(self, running: bool):
        if running:
            if not self._status_override:
                self.status_lbl.setText("Running")
                self.status_lbl.setObjectName("statusRunning")
                self.status_dot.setStyleSheet(f"background: {theme.GOOD}; border-radius: 5px;")
            self.run_btn.setText("Stop")
            self.run_btn.setObjectName("danger")
        else:
            if not self._status_override:
                self.status_lbl.setText("Stopped")
                self.status_lbl.setObjectName("statusStopped")
                self.status_dot.setStyleSheet(f"background: {theme.TEXT_DIM}; border-radius: 5px;")
            self.run_btn.setText("Start")
            self.run_btn.setObjectName("primary")
        self._repolish(self.status_lbl)
        self._repolish(self.run_btn)
        self._style_run_fab(running)

    @staticmethod
    def _repolish(w: QWidget):
        w.style().unpolish(w)
        w.style().polish(w)

    def _toggle_overlay(self, on: bool):
        if on:
            self.overlay.set_options(
                show_fov=self.settings.get("overlay_show_fov", True),
                show_crosshair=self.settings.get("overlay_show_crosshair", True),
                show_detections=self.settings.get("overlay_show_detections", True),
                fov_size=self.rows["fovSize"].value() if "fovSize" in self.rows else 640,
            )
            self.overlay.start()
            self.overlay_btn.setText("Disable Overlay")
        else:
            self.overlay.stop()
            self.overlay_btn.setText("Enable Overlay")
        self.settings.set("overlay_enabled", on)
        self.settings.save()

    def _open_config_file(self):
        path = self.config.path
        if path and os.path.isfile(path):
            os.startfile(path)  # noqa: S606
        else:
            self._append_console(f"\n[config] not found: {path}\n")

    def _refresh_style(self):
        self.setStyleSheet(theme.STYLE)
        for w in self.findChildren(QWidget):
            self._repolish(w)

    def _append_console(self, text: str):
        self.console.moveCursor(self.console.textCursor().MoveOperation.End)
        self.console.insertPlainText(text)
        self.console.moveCursor(self.console.textCursor().MoveOperation.End)

    def _pick_exe(self, edit: QLineEdit):
        start = os.path.dirname(edit.text()) if edit.text() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Select Inchro.exe", start,
                                              "Executables (*.exe)")
        if path:
            edit.setText(path)
            self._sync_paths()

    def _pick_cfg(self, edit: QLineEdit):
        start = os.path.dirname(edit.text()) if edit.text() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Select config.json", start,
                                              "JSON (*.json)")
        if path:
            edit.setText(path)
            self._apply_config_path(path, reload=True)

    def closeEvent(self, e):
        try:
            if self.settings.get("auto_save", True):
                self._do_save()
        finally:
            if self.backend.is_running():
                self.busy_overlay.show_busy("Stopping backend…")
                self.backend.stop_and_wait()
                self.busy_overlay.hide_busy()
            self.overlay.stop()
            self.overlay.close()
        super().closeEvent(e)
