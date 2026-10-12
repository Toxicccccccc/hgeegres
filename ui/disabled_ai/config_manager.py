"""Load/save the flat config this app shares with its engine.

Same contract as the reference UI: schema defaults are overlaid with the file,
unknown keys the engine may read are preserved, and writes are atomic so a
running engine never reads a half-written file.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from config_schema import all_fields, defaults, KEYBIND_NAME_TO_CODE


class ConfigManager:
    def __init__(self, path: str | None):
        self.path = path or ""
        self._field_types = {f["key"]: f["type"] for _, _, f in all_fields()}

    # ---- loading -----------------------------------------------------------
    def load(self) -> Dict[str, Any]:
        data = defaults()
        raw = self._read_raw()
        if raw:
            data.update(raw)  # file wins; unknown keys preserved
        return data

    def _read_raw(self) -> Dict[str, Any]:
        if not self.path or not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                obj = json.load(handle)
            return obj if isinstance(obj, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    # ---- saving ------------------------------------------------------------
    def save(self, values: Dict[str, Any]) -> None:
        if not self.path:
            return
        merged = self._read_raw() or defaults()
        for key, val in values.items():
            merged[key] = self._coerce(key, val)
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2)
        os.replace(tmp, self.path)

    def _coerce(self, key: str, val: Any) -> Any:
        t = self._field_types.get(key)
        try:
            if t == "keybind":
                return self._coerce_keybind(val)
            if t in ("int", "inttext"):
                return int(val)
            if t == "float":
                return float(val)
            if t == "bool":
                return bool(val)
            if t in ("string", "choice", "model", "color"):
                return str(val)
        except (TypeError, ValueError):
            return val
        return val

    def _coerce_keybind(self, val: Any, fallback: int = 0x12) -> int:
        if isinstance(val, bool):
            return fallback
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str):
            text = val.strip()
            if not text:
                return fallback
            name = text.split("(")[0].strip().lower()
            if name in KEYBIND_NAME_TO_CODE:
                return KEYBIND_NAME_TO_CODE[name]
            try:
                return int(text, 0)
            except ValueError:
                return fallback
        return fallback
