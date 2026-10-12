"""
Loads / saves Inchro's config.json.

Design goals:
  - Never lose keys the C++ backend reads but the UI does not model.
  - Tolerate a missing or malformed file (fall back to schema defaults).
  - Coerce values to the schema's type on save so the JSON stays clean.
"""

import json
import os
from typing import Any, Dict

from config_schema import all_fields, defaults, KEYBIND_NAME_TO_CODE


class ConfigManager:
    def __init__(self, path: str):
        self.path = path
        self._field_types = {f["key"]: f["type"] for _, _, f in all_fields()}

    # ---- loading -----------------------------------------------------------
    def load(self) -> Dict[str, Any]:
        """Return the full config dict (schema defaults overlaid with file)."""
        data = defaults()
        raw = self._read_raw()
        if raw:
            data.update(raw)  # file wins, and unknown keys are preserved
        # Normalize keybinds after merge (file may contain "Pad LT" strings).
        for key in ("keybind", "secondaryKeybind"):
            if key in data:
                fb = 0x02 if key == "keybind" else 0x01
                data[key] = self._coerce_keybind(data[key], fb)
        return data

    def _read_raw(self) -> Dict[str, Any]:
        if not self.path or not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            return obj if isinstance(obj, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _coerce_keybind(self, val: Any, fallback: int = 0x02) -> int:
        if isinstance(val, bool):
            return fallback
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            return int(val)
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return fallback
            # Accept "Pad LT", "pad lt", or "Pad LT  (0x10001)"
            name = s.split("(")[0].strip().lower()
            if name in KEYBIND_NAME_TO_CODE:
                return KEYBIND_NAME_TO_CODE[name]
            try:
                return int(s, 0)  # handles "0x10001" / "65537"
            except ValueError:
                return fallback
        return fallback

    # ---- saving ------------------------------------------------------------
    def save(self, values: Dict[str, Any]) -> None:
        """
        Merge `values` (only the keys we manage) onto whatever is already in
        the file and write it back, preserving formatting-friendly indentation
        and any keys we don't manage.
        """
        merged = self._read_raw()
        if not merged:
            merged = defaults()

        for key, val in values.items():
            merged[key] = self._coerce(key, val)

        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        # Write atomically to avoid the backend reading a half-written file.
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        os.replace(tmp, self.path)

    def _coerce(self, key: str, val: Any) -> Any:
        t = self._field_types.get(key)
        try:
            if t == "keybind":
                return self._coerce_keybind(val)
            if t == "int" or t == "inttext":
                return int(val)
            if t == "float":
                return float(val)
            if t == "bool":
                return bool(val)
            if t in ("string", "choice"):
                return str(val)
        except (TypeError, ValueError):
            return val
        return val
