"""Disabled AI main window.

Sidebar navigation over a stacked page area, schema-driven settings cards, and a
masthead that shows the same live numbers the engine already emits (FPS, latency,
target state, frame) so they stay visible on every page. The window owns no
engine logic: it drives the existing backends through the shared callback
contract.
"""

from __future__ import annotations

import os
import sys
import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from qt import (
    Qt, QTimer, QSize, QUrl, QEasingCurve, QPropertyAnimation,
    QParallelAnimationGroup, QDesktopServices, QIcon, QColor, QPainter,
    QPixmap, QFont, QComboBox, QDialog, QFileDialog, QMessageBox,
    QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea, QPlainTextEdit,
    QLineEdit, QCheckBox, QSizePolicy,
)

import theme
import nav_icons
from config_schema import SCHEMA
from config_manager import ConfigManager
from widgets import FieldRow, Card, HeaderStat
from movement_presets import PRESETS, get_preset
from game_catalog import GAMES, get_game, search_games, game_for_process
from game_art import render_cover_only, draw_card_footer, prefetch_all, clear_cache
from profiles import ProfileManager, ProfileEntry

# ui/disabled_ai/main_window.py -> project root is three levels up.
ROOT = Path(__file__).resolve().parents[2]

# Pages that are built from the schema; the rest are custom.
SCHEMA_PAGES = ("Aim", "Detection", "Triggerbot", "Capture", "Input & Device", "Overlay", "Advanced")
# There is no Overview serving page any more: the live figures it used to carry
# are pinned in the masthead (see _build_banner), so they stay visible on every
# page instead of hiding behind a menu item. "Profiles" and "Console" are the
# only bespoke pages left.
TAB_ORDER = ["Profiles", "Aim", "Detection", "Triggerbot", "Capture",
             "Input & Device", "Overlay", "Advanced", "Console"]

# Saved settings live under config/ so the project root stays uncluttered.
CONFIG_PATH = ROOT / "config" / "settings.json"
ASSET_DIR = ROOT / "assets"
PROFILES_DIR = ROOT / "config" / "profiles"
MODELS_DIR = ROOT / "models"
# The app logo is shown full-width across the top banner.
LOGO_PATH = ROOT / "assets" / "img_src" / "logo.png"
BANNER_HEIGHT = 76


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Disabled AI")
        self.resize(1180, 760)
        self.setMinimumSize(940, 620)
        if LOGO_PATH.is_file():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self.config = ConfigManager(str(CONFIG_PATH))
        self._values = self.config.load()
        self.rows: dict[str, FieldRow] = {}
        self.nav_buttons: list[QPushButton] = []
        self._collapsed = False
        self._fade_anim = None

        # One saved profile per game, under config/profiles/.
        self.profiles = ProfileManager(
            profiles_dir=str(PROFILES_DIR),
            models_dir=str(MODELS_DIR),
            live_config_path=lambda: str(CONFIG_PATH),
            gather_values=self._gather,
            reload_ui=self._reload_from_profile,
        )

        # Real-time save: every change is written straight away so the config on
        # disk always matches the UI (and a running native engine, which re-reads
        # the file every frame, picks the change up immediately). The timer is
        # only a coalescing window for a fast drag; the interval is short enough
        # that it still reads as instant.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(60)
        self._save_timer.timeout.connect(self._do_save)
        self._saved_at = 0.0

        self.engine = None
        self.engine_thread = None
        self.running = False
        # Set up the inter-thread plumbing up front so callbacks that arrive
        # before the engine starts never touch a missing attribute.
        self._messages = queue.Queue()
        self._preview_frames = queue.Queue(maxsize=2)
        self._latest_preview = None
        self._preview_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.preview_stop_event = threading.Event()
        self.preview_stop_event.set()
        self._backend = None
        self._load_engine_hooks()

        self._build()
        self._load_into_ui()
        self._select_tab(0)
        # The floating preview is a separate window; create it hidden and let the
        # Show Floating Preview toggle decide whether it appears.
        self._floating_preview = None
        self._sync_floating_preview()
        # The FOV guide is another separate overlay; same lazy-create pattern.
        self._fov_guide = None
        self._sync_fov_guide()

    # ---- engine integration -------------------------------------------------
    def _load_engine_hooks(self):
        """Import the existing backends lazily so the UI opens without CUDA."""
        self._backends_ready = False
        try:
            # The engine package lives under engine/; make sure it is importable
            # even when the UI is started without run_app.py.
            engine_dir = str(ROOT / "engine")
            if engine_dir not in sys.path:
                sys.path.insert(0, engine_dir)
            from disabledassistance import DisabledAssistanceEngine
            from disabledassistance_native import NativeEngineBackend, find_native_engine
            self._PythonEngine = DisabledAssistanceEngine
            self._NativeEngine = NativeEngineBackend
            self._find_native = find_native_engine
            self._backends_ready = True
        except Exception as exc:  # pragma: no cover - environment dependent
            self.log(f"Engine backends unavailable: {exc}")

    # ---- layout -------------------------------------------------------------
    def _build(self):
        # Outer column: a full-width logo banner on top, then the sidebar + pages
        # row beneath it. The banner spans the entire window width, so the logo
        # reads as the app's masthead rather than being boxed into the sidebar.
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_banner())

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        for tab in TAB_ORDER:
            if tab == "Profiles":
                self.stack.addWidget(self._build_profiles_page())
            elif tab == "Console":
                self.stack.addWidget(self._build_console())
            else:
                self.stack.addWidget(self._build_schema_page(tab))
        row.addWidget(self.stack, 1)
        column.addLayout(row, 1)

    def _build_banner(self) -> QFrame:
        """Full-width masthead: the logo fills the banner height on the left, with
        the app name and its one-line promise beside it."""
        banner = QFrame()
        banner.setObjectName("banner")
        banner.setFixedHeight(BANNER_HEIGHT)
        lay = QHBoxLayout(banner)
        lay.setContentsMargins(16, 4, 16, 4)
        lay.setSpacing(16)

        # The logo keeps its aspect ratio at the full banner height, so it reads
        # as the masthead mark rather than a small icon.
        self.banner_logo = QLabel()
        self.banner_logo.setObjectName("bannerLogo")
        self.banner_logo.setScaledContents(False)
        self.banner_logo.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        if LOGO_PATH.is_file():
            pixmap = QPixmap(str(LOGO_PATH))
            if not pixmap.isNull():
                self.banner_logo.setPixmap(
                    pixmap.scaledToHeight(BANNER_HEIGHT - 8,
                                          Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(self.banner_logo)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(0)
        title = QLabel("Disabled AI")
        title.setObjectName("bannerTitle")
        subtitle = QLabel("Neural enemy detection · humanised movement · 100% external")
        subtitle.setObjectName("bannerSubtitle")
        text_column.addWidget(title)
        text_column.addWidget(subtitle)
        lay.addLayout(text_column)
        lay.addStretch(1)

        # Live telemetry, pinned right in the masthead. This is the figures that
        # used to live on a separate Overview/Dashboard page, moved up here so
        # they stay visible while any settings page is open. self.tiles keeps the
        # same keys the engine callbacks already use (on_fps/on_latency/...), so
        # the message pump needs no change beyond who owns the labels.
        # Captions are plain ASCII: the bundled UI font has no glyph for the
        # arrow, so "CAPTURE → DETECT" rendered as a missing-glyph box.
        self.tiles = {
            "fps": HeaderStat("DETECTION RATE", "--", banner),
            "latency": HeaderStat("CAPTURE TO DETECT", "--", banner),
            "target": HeaderStat("TARGET STATE", "--", banner),
            "sequence": HeaderStat("FRAME", "--", banner),
        }
        # The target state is the one variable-width value ("Hold lock key",
        # "Settling", ...), so give it a floor and let the others stay tight.
        self.tiles["target"].setMinimumWidth(150)
        for stat in self.tiles.values():
            lay.addWidget(stat)
        return banner

    SIDEBAR_W = 216
    SIDEBAR_W_COLLAPSED = 64

    def _build_sidebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(self.SIDEBAR_W)
        bar.setStyleSheet(theme.SIDEBAR)
        self.sidebar = bar

        lay = QVBoxLayout(bar)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.setContentsMargins(10, 12, 10, 12)
        lay.setSpacing(3)

        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 0, 6)
        self.brand = QLabel("Disabled AI")
        self.brand.setObjectName("brand")
        header.addWidget(self.brand)
        header.addStretch(1)
        self.collapse_btn = QPushButton()
        self.collapse_btn.setObjectName("collapseBtn")
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.setFixedSize(34, 34)
        self.collapse_btn.setIconSize(QSize(18, 18))
        self.collapse_btn.setIcon(nav_icons.make_icon("collapse", theme.TEXT_DIM, 18))
        self.collapse_btn.setToolTip("Collapse sidebar")
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        header.addWidget(self.collapse_btn)
        self._header_row = header
        lay.addLayout(header)

        for index, name in enumerate(TAB_ORDER):
            button = self._make_nav_item(name)
            button.clicked.connect(lambda _=False, i=index: self._select_tab(i))
            self.nav_buttons.append(button)
            lay.addWidget(button)

        lay.addStretch(1)

        divider = QFrame()
        divider.setObjectName("navDivider")
        lay.addWidget(divider)
        lay.addSpacing(6)

        # Start / Stop, the only two actions that need to live everywhere.
        self.start_button = QPushButton("Start Engine")
        self.start_button.setObjectName("primary")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self.start_engine)
        lay.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("danger")
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_engine)
        lay.addWidget(self.stop_button)

        self.status_label = QLabel("Stopped")
        self.status_label.setObjectName("statusStopped")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.status_label)

        # Save Config: changes are written in real time, but this button forces an
        # immediate write (and gives the user something concrete to click).
        self.save_button = QPushButton("Save Config")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self.save_now)
        lay.addWidget(self.save_button)

        self.save_label = QLabel("Auto-save on")
        self.save_label.setObjectName("statusRunning")
        self.save_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.save_label.setToolTip("Every change is written to the config file immediately.")
        lay.addWidget(self.save_label)
        return bar

    def _nav_text(self, name: str) -> str:
        return "  " + name.replace("&", "&&")

    def _make_nav_item(self, name: str) -> QPushButton:
        button = QPushButton(self._nav_text(name))
        button.setObjectName("navItem")
        button.setProperty("navName", name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIconSize(QSize(20, 20))
        button.setIcon(nav_icons.make_icon(nav_icons.TAB_ICON.get(name, "sliders"),
                                           theme.TEXT_DIM, 20))
        button.setToolTip(name)
        button.setMinimumHeight(38)
        return button

    def _toggle_sidebar(self):
        self._collapsed = not self._collapsed
        target = self.SIDEBAR_W_COLLAPSED if self._collapsed else self.SIDEBAR_W
        start = self.sidebar.width()

        self.collapse_btn.setIcon(
            nav_icons.make_icon("expand" if self._collapsed else "collapse",
                                theme.TEXT_DIM, 18)
        )
        self.collapse_btn.setToolTip("Expand sidebar" if self._collapsed else "Collapse sidebar")
        self.brand.setVisible(not self._collapsed)

        for button in self.nav_buttons:
            name = button.property("navName")
            button.setText("" if self._collapsed else self._nav_text(name))
            button.setProperty("collapsed", self._collapsed)
            theme.repolish(button)

        group = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self.sidebar, prop, self)
            anim.setDuration(200)
            anim.setStartValue(start)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            group.addAnimation(anim)
        group.start()
        self._sidebar_anim = group

    def _select_tab(self, index: int):
        if not (0 <= index < self.stack.count()):
            return
        self.stack.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setProperty("selected", position == index)
            theme.repolish(button)
        # Fade the incoming page for a soft transition.
        page = self.stack.currentWidget()
        if page is not None:
            theme.fade_in(page, 150)

    # ---- pages --------------------------------------------------------------
    def _scroll_page(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(theme.SCROLL)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("tabHeader")
        lay.addWidget(heading)
        scroll.setWidget(page)
        return scroll, lay

    def _build_schema_page(self, tab: str) -> QWidget:
        scroll, lay = self._scroll_page(tab)
        # The Aim page leads with movement presets, which fill the sliders below.
        quick_card = None
        advanced_layout = None
        advanced_host = None
        if tab == "Aim":
            lay.addWidget(self._build_preset_card())
            quick_card = Card(
                "Quick setup",
                "Start with these controls. All detailed tuning stays available below.",
            )
            quick_hint = QLabel(
                "The FOV guide is the search area. Hold your Lock key to follow a "
                "detected target inside it. If the status says detections are outside "
                "the FOV, increase Search area or move the crosshair."
            )
            quick_hint.setObjectName("hint")
            quick_hint.setWordWrap(True)
            quick_card.add_widget(quick_hint)
            lay.addWidget(quick_card)

            advanced_button = QPushButton("Show all aim controls")
            advanced_button.setCheckable(True)
            advanced_button.setObjectName("ghost")
            advanced_button.setCursor(Qt.CursorShape.PointingHandCursor)
            advanced_button.setToolTip(
                "Open the detailed movement, prediction, target-selection, and filter controls."
            )
            lay.addWidget(advanced_button)

            advanced_host = QWidget()
            advanced_layout = QVBoxLayout(advanced_host)
            advanced_layout.setContentsMargins(0, 0, 0, 0)
            advanced_layout.setSpacing(12)
            advanced_host.setVisible(False)
            lay.addWidget(advanced_host)

            def _toggle_advanced(visible: bool) -> None:
                advanced_host.setVisible(visible)
                advanced_button.setText(
                    "Hide detailed aim controls" if visible else "Show all aim controls"
                )

            advanced_button.toggled.connect(_toggle_advanced)

        for card_def in SCHEMA.get(tab, []):
            card = Card(card_def["title"], card_def.get("subtitle", ""))
            has_advanced_fields = False
            for field in card_def["fields"]:
                display_field = field
                if tab == "Aim" and field.get("simple_label"):
                    display_field = {**field, "label": field["simple_label"]}
                row = FieldRow(display_field)
                row.changed.connect(self._on_field_changed)
                self.rows[field["key"]] = row
                if tab == "Aim" and field.get("simple"):
                    quick_card.add_row(row)
                else:
                    card.add_row(row)
                    has_advanced_fields = True
            if tab == "Aim":
                if has_advanced_fields:
                    advanced_layout.addWidget(card)
            else:
                lay.addWidget(card)
        lay.addStretch(1)
        self._wire_visibility(tab)
        return scroll

    def _build_preset_card(self) -> Card:
        """Movement presets: one click fills in the movement sliders below."""
        card = Card("Movement Presets",
                    "Pick a ready-made feel; the sliders below fill in automatically.")
        row = QHBoxLayout()
        self.preset_combo = QComboBox()
        for preset in PRESETS:
            self.preset_combo.addItem(preset.name, preset.id)
        self.preset_combo.setToolTip(
            "A preset is a bundle of movement settings with a friendly name. "
            "Choosing one still lets you tweak every slider afterwards."
        )
        row.addWidget(self.preset_combo, 1)
        apply_btn = QPushButton("Apply Preset")
        apply_btn.setObjectName("primary")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_preset)
        row.addWidget(apply_btn)
        host = QWidget()
        host.setLayout(row)
        card.add_widget(host)
        self.preset_hint = QLabel(PRESETS[0].description)
        self.preset_hint.setObjectName("hint")
        self.preset_hint.setWordWrap(True)
        card.add_widget(self.preset_hint)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        return card

    def _on_preset_selected(self, _index: int) -> None:
        preset = get_preset(self.preset_combo.currentData())
        if preset is not None:
            self.preset_hint.setText(preset.description)

    def _apply_preset(self) -> None:
        preset = get_preset(self.preset_combo.currentData())
        if preset is None or not preset.values:
            self.log("Preset 'Custom' keeps your current values.")
            return
        for key, value in preset.values.items():
            row = self.rows.get(key)
            if row is not None:
                row.set_value(value)
        self._on_field_changed()
        self.log(f"Applied movement preset: {preset.name}")

    def _wire_visibility(self, tab: str):
        """Hide dependent fields until their controlling field matches."""
        for card_def in SCHEMA.get(tab, []):
            for field in card_def["fields"]:
                when = field.get("visible_when")
                if not when:
                    continue
                controller = self.rows.get(when)
                if controller is None:
                    continue
                target = self.rows[field["key"]]

                def _refresh(controller=controller, target=target, field=field):
                    allowed = field.get("visible_for", [])
                    value = controller.value()
                    # BOOL_VISIBLE_ON lists "True"; a bool controller (e.g. the
                    # kalman_enabled toggle) must map to that spelling, not
                    # Python's "True"/"False" repr, or the dependent fields would
                    # never appear. String settings still compare directly.
                    if isinstance(value, bool):
                        value = "True" if value else "False"
                    target.setVisible(str(value) in [str(a) for a in allowed])

                controller.changed.connect(_refresh)
                # Keep the refresher so it can be re-run after the saved values
                # are loaded. At build time every control still holds its schema
                # default (a checkbox is unchecked), so a field gated on a toggle
                # that defaults to true -- the Kalman controls -- would start
                # hidden until the user touched the toggle. _load_into_ui()
                # re-runs these once the real values are in place.
                if not hasattr(self, "_visibility_refreshers"):
                    self._visibility_refreshers = []
                self._visibility_refreshers.append(_refresh)
                _refresh()

    # The Overview/Dashboard page was removed: its live figures now live in the
    # masthead (see _build_banner), and the live preview is available only as the
    # floating window controlled by the Overlay toggles.

    def _build_profiles_page(self) -> QWidget:
        from profiles_page import ProfilesPage
        self.profiles_page = ProfilesPage(self.profiles)
        return self.profiles_page

    def _reload_from_profile(self) -> None:
        """Load the active profile's values into the widgets (called by the manager)."""
        active = self.profiles.active_filename()
        if not active:
            return
        values = self.profiles.load_values(active)
        self._values.update(values)
        self._load_into_ui()
        if getattr(self, "profiles_page", None) is not None:
            self.profiles_page.refresh(force=True)
        self.log(f"Loaded profile: {active}")

    def _build_console(self) -> QWidget:
        scroll, lay = self._scroll_page("Console")
        card = Card("Engine Output", "Everything the engine reports, in order.")
        self.console = QPlainTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(420)
        card.add_widget(self.console)
        lay.addWidget(card)
        lay.addStretch(1)
        return scroll

    # ---- config io ----------------------------------------------------------
    # Schema keys that stand for more than one config key. The resolution field
    # is a single control over screen_res_x + screen_res_y, so it is expanded
    # into both flat keys on save and rebuilt from them on load.
    def _load_into_ui(self):
        for key, row in self.rows.items():
            field = getattr(row, "field", {})
            keys = field.get("keys")
            if keys and field.get("type") == "resolution":
                width = self._values.get(keys[0], 2560)
                height = self._values.get(keys[1], 1440)
                row.set_value((width, height))
            elif key in self._values:
                row.set_value(self._values[key])
        # set_value() blocks signals, so the visibility rules built during
        # _build() did not see the loaded values. Re-run them now so a field
        # gated on a control that is on by default (the Kalman sub-options) is
        # shown immediately instead of waiting for the first toggle.
        self._refresh_visibility()

    def _refresh_visibility(self) -> None:
        """Re-evaluate every visible_when rule after values change."""
        for refresh in getattr(self, "_visibility_refreshers", []):
            try:
                refresh()
            except RuntimeError:
                pass

    def _gather(self) -> dict:
        values = {}
        for key, row in self.rows.items():
            field = getattr(row, "field", {})
            value = row.value()
            keys = field.get("keys")
            if keys and field.get("type") == "resolution":
                # A resolution control owns two flat keys; write both so the
                # engine sees a consistent width/height pair.
                try:
                    width, height = value
                except (TypeError, ValueError):
                    width, height = 2560, 1440
                values[keys[0]] = int(width)
                values[keys[1]] = int(height)
            else:
                values[key] = value
        return values

    def _on_field_changed(self):
        self._values.update(self._gather())
        # Real-time save: write immediately, then coalesce any further changes
        # from the same fast drag into one follow-up write. This keeps the disk
        # in step with the UI without ever lagging behind a single change.
        self._do_save()
        self._save_timer.start()
        # React to the preview toggles straight away so ticking "Show Floating
        # Preview" (or "Keep Preview On Top") takes effect without a restart.
        self._sync_floating_preview()
        # The FOV guide must track the FOV/shape/colour/offset sliders live, so
        # the on-screen box always shows exactly where the engine is looking.
        self._sync_fov_guide()
        # Push the geometry change to a running engine so the detection zone
        # matches the guide in real time instead of on the next restart.
        self._push_live_geometry()

    def _sync_fov_guide(self) -> None:
        """Show, hide, and re-geometry the on-screen FOV guide."""
        want = bool(self._values.get("show_fov", True))
        if want and self._fov_guide is None:
            from fov_guide import FovGuide
            self._fov_guide = FovGuide()
        if self._fov_guide is None:
            return
        self._fov_guide.apply(
            fov=self._values.get("fov"),
            shape=self._values.get("fov_shape"),
            color=self._values.get("fov_color"),
            offset_x=self._values.get("offset_x"),
            offset_y=self._values.get("offset_y"),
        )
        if want and not self._fov_guide.isVisible():
            self._fov_guide.show()
        elif not want and self._fov_guide.isVisible():
            self._fov_guide.hide()

    def _push_live_geometry(self) -> None:
        """Send live-tunable capture geometry to a running engine.

        The native engine re-reads its config file every quarter second, so the
        simplest correct path is to rewrite that file; the Python engine exposes
        ``update_settings`` directly. Either way the detection zone follows the
        FOV slider within a frame instead of waiting for a restart.
        """
        engine = self.engine
        if engine is None or not self.running:
            return
        try:
            engine.update_settings(self._settings_for_engine())
        except Exception as exc:  # pragma: no cover - engine dependent
            self.log(f"Live update failed: {exc}")

    def _sync_floating_preview(self) -> None:
        """Show, hide, or restyle the floating preview to match the settings."""
        want = bool(self._values.get("floating_preview", True))
        on_top = bool(self._values.get("always_on_top", True))
        if want and self._floating_preview is None:
            from preview_window import FloatingPreview
            self._floating_preview = FloatingPreview(on_top=on_top)
            # Park it near the top-right of the primary screen the first time.
            screen = QApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self._floating_preview.move(area.right() - 320, area.top() + 60)
        if self._floating_preview is None:
            return
        self._floating_preview.set_on_top(on_top)
        if want and not self._floating_preview.isVisible():
            self._floating_preview.show()
        elif not want and self._floating_preview.isVisible():
            self._floating_preview.hide()

    def _do_save(self):
        try:
            self.config.save(self._gather())
            self._saved_at = time.time()
            if getattr(self, "save_label", None) is not None:
                self.save_label.setText("Saved  ✓")
                self.save_label.setObjectName("statusRunning")
                theme.repolish(self.save_label)
        except OSError as exc:
            self.log(f"Could not save config: {exc}")
            if getattr(self, "save_label", None) is not None:
                self.save_label.setText(f"Save failed: {exc}")
                self.save_label.setObjectName("statusStopped")
                theme.repolish(self.save_label)

    def save_now(self):
        """Write the current UI values to disk right now (Save Config button)."""
        self._values.update(self._gather())
        self._do_save()
        self.log(f"Saved config to {CONFIG_PATH}")

    # ---- engine control -----------------------------------------------------
    def _settings_for_engine(self) -> dict:
        values = dict(self._values)
        values.update(self._gather())
        # Map schema keys onto the engine's flat keys.
        values["ScreenResX"] = int(values.get("screen_res_x", 2560))
        values["ScreenResY"] = int(values.get("screen_res_y", 1440))
        return values

    def _callbacks(self) -> dict:
        """The contract both engine backends already speak."""
        return dict(
            on_status=lambda text: self._messages.put(("status", text)),
            on_detection=lambda text: self._messages.put(("detection", text)),
            on_preview=self._queue_preview,
            on_fps=lambda value: self._messages.put(("fps", value)),
            on_pipeline_metrics=lambda value: self._messages.put(("pipeline", value)),
            on_latency=lambda value: self._messages.put(("latency", value)),
        )

    def _backend_for_model(self, model_path: str) -> str:
        suffix = Path(str(model_path)).suffix.lower()
        if suffix == ".engine" and self._find_native() is not None:
            return "native"
        return "python"

    def _create_engine(self):
        values = self._settings_for_engine()
        callbacks = self._callbacks()
        native_path = self._find_native()
        if self._backend_for_model(values.get("model_path", "")) == "native" and native_path:
            self._backend = "native"
            return self._NativeEngine(executable=native_path, **callbacks)
        self._backend = "python"
        return self._PythonEngine(**callbacks)

    def start_engine(self):
        if self.running:
            return
        if not self._backends_ready:
            self.log("Engine backends are not available in this environment.")
            return
        self._do_save()
        # Stop any previous engine before replacing it.
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception:
                pass
        try:
            self.engine = self._create_engine()
        except Exception as exc:
            self.log(f"Could not create the engine: {exc}")
            return
        self.engine.update_settings(self._settings_for_engine())

        self.stop_event = threading.Event()
        self.preview_stop_event = threading.Event()
        self._messages = queue.Queue()
        self._preview_frames = queue.Queue(maxsize=2)
        self._latest_preview = None
        self._preview_lock = threading.Lock()

        self.engine_thread = threading.Thread(target=self._run_engine, daemon=True)
        self.engine_thread.start()
        self.preview_thread = threading.Thread(target=self._process_preview, daemon=True)
        self.preview_thread.start()

        # One message pump for the window's whole life. Creating a fresh QTimer on
        # every Start left the previous one alive (parented to self, still firing)
        # and, worse, meant the timer the Stop path touched could be a different
        # object from the one draining messages -- part of why Start/Stop broke
        # after the first run. A single reused timer fixes both.
        if getattr(self, "_message_timer", None) is None:
            self._message_timer = QTimer(self)
            self._message_timer.setInterval(40)
            self._message_timer.timeout.connect(self._drain_messages)
        self._message_timer.start()

        self.running = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._set_status("Running", running=True)
        self.log("Engine started.")

    def _run_engine(self):
        try:
            self.engine.run(self.stop_event)
        except Exception as exc:
            self._messages.put(("error", str(exc)))
        finally:
            self._messages.put(("finished", None))

    def stop_engine(self):
        if self.engine is None:
            return
        self.log("Stopping engine…")
        self.stop_event.set()
        self.preview_stop_event.set()
        self.stop_button.setEnabled(False)
        # Do NOT stop the message timer here. The worker thread signals it has
        # really exited by posting a "finished" message, and only that message
        # re-enables Start. Stopping the timer immediately meant the final
        # "finished" was never drained, so after the first Stop the window still
        # believed it was running and Start stayed disabled forever -- the
        # reported "start and stop stop working after the first run". The timer
        # is stopped inside _drain_messages once "finished" has been handled.

    # ---- preview pipeline (off the GUI thread) ------------------------------
    def _queue_preview(self, frame, boxes=None):
        if getattr(self, "preview_stop_event", None) is None or self.preview_stop_event.is_set():
            return
        item = (frame.copy(), list(boxes) if boxes else [])
        try:
            self._preview_frames.put_nowait(item)
        except queue.Full:
            try:
                self._preview_frames.get_nowait()
            except queue.Empty:
                pass

    def _process_preview(self):
        while not self.preview_stop_event.is_set():
            try:
                frame, boxes = self._preview_frames.get(timeout=0.1)
            except queue.Empty:
                continue
            except (TypeError, ValueError):
                continue
            try:
                while True:
                    newer = self._preview_frames.get_nowait()
                    if isinstance(newer, tuple) and len(newer) == 2:
                        frame, boxes = newer
            except queue.Empty:
                pass
            try:
                if not isinstance(frame, np.ndarray) or frame.ndim != 3:
                    continue
                # Draw on the frame EXACTLY as it arrived. Both engines already
                # emit boxes in the pixel space of the image they stream (the
                # native engine scales them into the downsampled preview; the
                # Python engine into its FOV crop), so the frame's own size IS the
                # box space. Resizing the frame to a fixed square before drawing
                # -- and then scaling boxes by that square -- is what made the
                # boxes drift off the target (the reported preview "zoom"). Keep
                # the streamed pixels and scale by the real decoded size instead.
                source_h, source_w = frame.shape[0], frame.shape[1]
                source_size = float(max(source_h, source_w, 1))
                image = frame
                overlay = self._values.get("preview_overlay", True)
                if overlay:
                    self._draw_preview_boxes(image, boxes or [], source_size, source_size)
                ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
                if ok:
                    with self._preview_lock:
                        self._latest_preview = encoded.tobytes()
            except (cv2.error, ValueError, TypeError):
                continue

    def _draw_preview_boxes(self, image, boxes, size, source_size: float) -> None:
        """Draw body box, head box, label, and a line to the crosshair.

        ``boxes`` are in ``source_size`` pixels (the space the engine measured
        them in). Rather than rescaling the image to match, the boxes are scaled
        by the image's OWN size over ``source_size``, so they land on the correct
        pixels no matter how large the streamed frame is. The crosshair is the
        centre of the captured square. The distance line makes it obvious how far
        each detection is from where the player aims.

        ``size`` is accepted for callers that pass the drawn image's pixel size;
        it is used only as a crosshair fallback when the image's own size is
        unavailable.
        """
        draw_h, draw_w = image.shape[0], image.shape[1]
        draw_w = int(draw_w) if draw_w else int(size)
        draw_h = int(draw_h) if draw_h else int(size)
        scale = draw_w / float(max(source_size, 1.0))
        center = (draw_w // 2, draw_h // 2)
        show_heads = self._values.get("preview_head_box", True)
        show_lines = self._values.get("preview_distance_line", True)
        show_confidence = self._values.get("preview_show_confidence", True)
        show_distance = self._values.get("preview_show_distance", True)
        rainbow = self._values.get("preview_rainbow", False)
        crosshair_style = self._values.get("preview_crosshair_style", "Cross")
        crosshair_size = int(self._values.get("preview_crosshair_size", 12))
        crosshair_qcolor = QColor(self._values.get("preview_crosshair_color", "#FFFFFF"))
        if not crosshair_qcolor.isValid():
            crosshair_qcolor = QColor("#FFFFFF")
        crosshair_color = (
            crosshair_qcolor.blue(),
            crosshair_qcolor.green(),
            crosshair_qcolor.red(),
        )

        def rainbow_color(phase: float):
            hue = int((time.perf_counter() * 60.0 + phase * 29.0) % 180)
            hsv = np.uint8([[[hue, 220, 255]]])
            bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
            return tuple(int(channel) for channel in bgr)

        # Keep the nearest (lowest) box index as the "primary" target.
        primary = 0
        if len(boxes) > 1:
            primary = min(
                range(len(boxes)),
                key=lambda i: abs(((boxes[i][0] + boxes[i][2]) * 0.5 * scale) - center[0])
                + abs(((boxes[i][1] + boxes[i][3]) * 0.5 * scale) - center[1]),
            )

        for index, (x1, y1, x2, y2, confidence, _cls) in enumerate(boxes):
            left = int(round(min(x1, x2) * scale))
            right = int(round(max(x1, x2) * scale))
            top = int(round(min(y1, y2) * scale))
            bottom = int(round(max(y1, y2) * scale))
            is_primary = index == primary

            body_colour = (
                rainbow_color(index)
                if rainbow
                else (60, 220, 60) if is_primary else (200, 170, 60)
            )
            cv2.rectangle(image, (left, top), (right, bottom), body_colour, 2 if is_primary else 1)

            # Head box: the top ~18% of the body box, which is where the aim
            # point sits. Drawing it makes the vertical aim target visible.
            if show_heads:
                head_bottom = top + max(2, int((bottom - top) * 0.18))
                cv2.rectangle(image, (left, top), (right, head_bottom), (80, 200, 255), 1)

            # Distance line from the crosshair to the box centre.
            box_cx = (left + right) // 2
            box_cy = (top + bottom) // 2
            if show_lines:
                line_colour = (60, 220, 60) if is_primary else (120, 120, 120)
                cv2.line(image, center, (box_cx, box_cy), line_colour, 1, cv2.LINE_AA)
                cv2.circle(image, (box_cx, box_cy), 2, line_colour, -1)

            label_parts = []
            if show_confidence:
                label_parts.append(f"{confidence * 100:.0f}%")
            if show_distance:
                distance = float(np.hypot(
                    (x1 + x2) * 0.5 - source_size * 0.5,
                    (y1 + y2) * 0.5 - source_size * 0.5,
                ))
                label_parts.append(f"{distance:.0f}px")
            if label_parts:
                cv2.putText(image, " ".join(label_parts), (left, max(top - 4, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, body_colour, 1, cv2.LINE_AA)

        # Crosshair marker at the capture centre.
        if rainbow:
            crosshair_color = rainbow_color(len(boxes))
        if crosshair_style in ("Cross", "Cross + Dot"):
            cv2.drawMarker(
                image,
                center,
                crosshair_color,
                cv2.MARKER_CROSS,
                crosshair_size,
                1,
                cv2.LINE_AA,
            )
        if crosshair_style in ("Dot", "Cross + Dot"):
            cv2.circle(image, center, max(1, crosshair_size // 8), crosshair_color, -1, cv2.LINE_AA)
        if crosshair_style == "Circle":
            cv2.circle(image, center, max(2, crosshair_size // 2), crosshair_color, 1, cv2.LINE_AA)

    def _drain_messages(self):
        while True:
            try:
                kind, value = self._messages.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.log(value)
            elif kind == "fps":
                self.on_fps(value)
            elif kind == "latency":
                self.on_latency(value)
            elif kind == "detection":
                self.on_detection(value)
            elif kind == "pipeline":
                self.on_pipeline(value)
            elif kind == "error":
                self.log(f"Engine error: {value}")
            elif kind == "finished":
                self.running = False
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self._set_status("Stopped", running=False)
                self.log("Engine stopped.")
                # The worker has exited; there is nothing left to drain, so stop
                # the pump here (it is restarted by the next start_engine).
                if hasattr(self, "_message_timer"):
                    self._message_timer.stop()
        # Paint the newest decoded preview.
        data = None
        if getattr(self, "_latest_preview", None) is not None:
            with self._preview_lock:
                data = self._latest_preview
                self._latest_preview = None
        if data:
            # The only preview surface now is the floating window (the Overlay
            # toggle). With no Overview page there is no embedded label to feed,
            # so a decoded frame goes straight to the floating window when it is
            # open and is otherwise dropped.
            if getattr(self, "_floating_preview", None) is not None \
                    and self._floating_preview.isVisible():
                self._floating_preview.set_image(data)
        if self.running:
            # Started by start_engine; a no-op while it is already running.
            if not self._message_timer.isActive():
                self._message_timer.start()

    def test_send(self):  # pragma: no cover - wired later
        pass

    # ---- live hooks ---------------------------------------------------------
    def on_fps(self, value: float):
        self.tiles["fps"].set_value(f"{value:.0f} fps")

    def on_latency(self, value: float):
        self.tiles["latency"].set_value(f"{value:.1f} ms")

    def on_detection(self, text: str):
        # The engine status is a full sentence ("Target center: (x, y) aim error: "
        # ... aim status: Hold lock key"). The header has room for a couple of
        # words, so condense it: prefer the trailing aim status ("Ready",
        # "Holding...", "Settling..."), otherwise the leading phrase. The whole
        # line is kept as a tooltip. Without this the tile showed a truncated
        # mid-word fragment such as "Selected 91% (12".
        text = (text or "").strip()
        compact = text
        if "aim status:" in text:
            compact = text.split("aim status:")[-1]
        elif "(" in text:
            compact = text.split("(")[0]
        compact = compact.strip()
        if len(compact) > 22:
            compact = compact[:21].rstrip() + "…"
        self.tiles["target"].set_value(compact or "--")
        self.tiles["target"].setToolTip(text)

    def on_pipeline(self, value: dict):
        self.tiles["sequence"].set_value(f"#{value.get('sequence', 0)}")

    def log(self, text: str):
        widget = getattr(self, "console", None)
        if widget is not None:
            widget.appendPlainText(text)

    def _set_status(self, text: str, running: bool):
        self.status_label.setText(text)
        self.status_label.setObjectName("statusRunning" if running else "statusStopped")
        theme.repolish(self.status_label)

    def closeEvent(self, event):
        # Stop every thread and timer before Qt tears the widgets down: a timer
        # firing during destruction would touch deleted widgets.
        try:
            self.stop_event.set()
            self.preview_stop_event.set()
        except AttributeError:
            pass
        for name in ("_message_timer", "_save_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                try:
                    timer.stop()
                except (RuntimeError, AttributeError):
                    pass
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception:
                pass
        if hasattr(self, "console"):
            try:
                self.config.save(self._gather())
            except OSError:
                pass
        if getattr(self, "_floating_preview", None) is not None:
            try:
                self._floating_preview.close()
            except (RuntimeError, AttributeError):
                pass
        if getattr(self, "_fov_guide", None) is not None:
            try:
                self._fov_guide.close()
            except (RuntimeError, AttributeError):
                pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    theme.apply(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
