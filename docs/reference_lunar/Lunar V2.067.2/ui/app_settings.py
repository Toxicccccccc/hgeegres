"""
UI-local settings. Stores paths to the Lunar V2 backend exe and config.json.
"""

import json
import os
from typing import Any, Dict

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_PATH = os.path.join(_APP_DIR, "lunar_ui_settings.json")

_DEFAULT_RELEASE = os.path.normpath(os.path.join(_APP_DIR, "..", "backend", "x64", "Release"))

DEFAULTS: Dict[str, Any] = {
    "config_path": os.path.join(_DEFAULT_RELEASE, "config.json"),
    "exe_path": os.path.join(_DEFAULT_RELEASE, "LunarV2.exe"),
    "overlay_enabled": False,
    "overlay_show_fov": True,
    "overlay_show_crosshair": True,
    "overlay_show_detections": True,
    "auto_save": True,
    "cached_username": "",
}


class AppSettings:
    def __init__(self):
        self.data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self):
        if os.path.isfile(_SETTINGS_PATH):
            try:
                with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                if isinstance(obj, dict):
                    self.data.update(obj)
            except (OSError, json.JSONDecodeError):
                pass

    def save(self):
        try:
            with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except OSError:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any):
        self.data[key] = value
