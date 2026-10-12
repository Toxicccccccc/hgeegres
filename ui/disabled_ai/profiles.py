"""Per-game config profiles.

Each profile is a full copy of the settings for one game, stored as JSON under
``config/profiles/``. An index file records which profile is active, plus the
per-profile options (auto-save, auto-load, and an optional model). Switching
game is then one click instead of re-tuning every slider.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from config_schema import defaults
from game_catalog import get_game

_INDEX_NAME = "_index.json"
_BACKUP_CONFIG = "_unload_config.json"
_RESERVED = {_INDEX_NAME, _BACKUP_CONFIG}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ProfileEntry:
    filename: str
    game_id: str
    display_name: str
    updated: str
    active: bool = False
    auto_save: bool = True
    auto_load: bool = True
    model_file: str = ""

    @property
    def label(self) -> str:
        stem = self.filename[:-5]
        if stem == self.game_id:
            return self.display_name
        if stem.startswith(self.game_id) and len(stem) > len(self.game_id):
            return f"{self.display_name} ({stem[len(self.game_id):]})"
        return self.display_name

    @property
    def has_model(self) -> bool:
        return bool(self.model_file)


class ProfileManager:
    def __init__(
        self,
        profiles_dir: str,
        models_dir: str,
        live_config_path: Callable[[], str],
        gather_values: Callable[[], dict[str, Any]],
        reload_ui: Callable[[], None],
    ):
        self.profiles_dir = profiles_dir
        self.models_dir = models_dir
        self._live_config_path = live_config_path
        self._gather_values = gather_values
        self._reload_ui = reload_ui
        self._index_path = os.path.join(profiles_dir, _INDEX_NAME)
        os.makedirs(profiles_dir, exist_ok=True)
        os.makedirs(models_dir, exist_ok=True)

    # ---- index -------------------------------------------------------------
    def _read_index(self) -> dict[str, Any]:
        if not os.path.isfile(self._index_path):
            return {"active": "", "entries": {}}
        try:
            with open(self._index_path, "r", encoding="utf-8") as handle:
                obj = json.load(handle)
            if isinstance(obj, dict):
                obj.setdefault("active", "")
                obj.setdefault("entries", {})
                return obj
        except (OSError, json.JSONDecodeError):
            pass
        return {"active": "", "entries": {}}

    def _write_index(self, data: dict[str, Any]) -> None:
        tmp = self._index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp, self._index_path)

    def _entry_meta(self, filename: str) -> dict[str, Any]:
        return dict(self._read_index().get("entries", {}).get(filename, {}))

    def _upsert_entry(self, filename: str, game_id: str, display_name: str,
                      *, preserve: bool = True) -> None:
        index = self._read_index()
        previous = index["entries"].get(filename, {}) if preserve else {}
        index["entries"][filename] = {
            "game_id": game_id,
            "display_name": display_name,
            "updated": _utc_now(),
            "auto_save": previous.get("auto_save", True),
            "auto_load": previous.get("auto_load", True),
            "model_file": previous.get("model_file", ""),
        }
        self._write_index(index)

    def update_profile_settings(self, filename: str, *, auto_save=None, auto_load=None) -> ProfileEntry:
        index = self._read_index()
        entry = index["entries"].setdefault(filename, {})
        if auto_save is not None:
            entry["auto_save"] = auto_save
        if auto_load is not None:
            entry["auto_load"] = auto_load
        entry["updated"] = _utc_now()
        self._write_index(index)
        return self.get_profile(filename)

    def active_filename(self) -> str:
        return self._read_index().get("active", "") or ""

    def set_active(self, filename: str) -> None:
        index = self._read_index()
        index["active"] = filename
        self._write_index(index)

    # ---- paths -------------------------------------------------------------
    def _profile_path(self, filename: str) -> str:
        return os.path.join(self.profiles_dir, filename)

    def _model_path(self, model_file: str) -> str:
        return os.path.join(self.models_dir, model_file)

    def model_filename_for_profile(self, filename: str) -> str:
        return filename[:-5] + os.path.splitext(self._entry_meta(filename).get("model_file", ""))[1] \
            if self._entry_meta(filename).get("model_file") else filename[:-5] + ".onnx"

    def _scan_profile_files(self) -> list[str]:
        if not os.path.isdir(self.profiles_dir):
            return []
        names = [n for n in os.listdir(self.profiles_dir)
                 if n.lower().endswith(".json") and n not in _RESERVED]
        names.sort(key=lambda n: n.lower())
        return names

    def next_filename(self, game_id: str) -> str:
        slug = game_id.strip().lower().replace(" ", "_")
        first = f"{slug}.json"
        if not os.path.isfile(self._profile_path(first)):
            return first
        n = 1
        while os.path.isfile(self._profile_path(f"{slug}{n}.json")):
            n += 1
        return f"{slug}{n}.json"

    def _build_entry(self, filename: str, meta: dict[str, Any], active: str) -> ProfileEntry:
        game_id = meta.get("game_id", "")
        display_name = meta.get("display_name", "")
        if not game_id:
            game_id = filename[:-5].rstrip("0123456789") or "custom"
        if not display_name:
            game = get_game(game_id)
            display_name = game.name if game else filename[:-5].replace("_", " ").title()
        return ProfileEntry(
            filename=filename,
            game_id=game_id,
            display_name=display_name,
            updated=meta.get("updated", ""),
            active=filename == active,
            auto_save=bool(meta.get("auto_save", True)),
            auto_load=bool(meta.get("auto_load", True)),
            model_file=str(meta.get("model_file", "") or ""),
        )

    def list_profiles(self) -> list[ProfileEntry]:
        index = self._read_index()
        active = index.get("active", "")
        entries = index.get("entries", {})
        return [self._build_entry(name, entries.get(name, {}), active)
                for name in self._scan_profile_files()]

    def list_profiles_for_game(self, game_id: str) -> list[ProfileEntry]:
        return [p for p in self.list_profiles() if p.game_id == game_id]

    def get_profile(self, filename: str) -> ProfileEntry:
        index = self._read_index()
        if not os.path.isfile(self._profile_path(filename)):
            raise KeyError(filename)
        return self._build_entry(filename, index.get("entries", {}).get(filename, {}),
                                 index.get("active", ""))

    # ---- load / save -------------------------------------------------------
    def load_values(self, filename: str) -> dict[str, Any]:
        try:
            with open(self._profile_path(filename), "r", encoding="utf-8") as handle:
                obj = json.load(handle)
            return obj if isinstance(obj, dict) else dict(defaults())
        except (OSError, json.JSONDecodeError):
            return dict(defaults())

    def _write_profile(self, filename: str, values: dict[str, Any]) -> None:
        path = self._profile_path(filename)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(values, handle, indent=2)
        os.replace(tmp, path)

    def _backup_live(self) -> None:
        live = self._live_config_path()
        backup = os.path.join(self.profiles_dir, _BACKUP_CONFIG)
        if os.path.isfile(live):
            shutil.copy2(live, backup)

    def can_unload(self) -> bool:
        return os.path.isfile(os.path.join(self.profiles_dir, _BACKUP_CONFIG))

    def activate(self, filename: str, *, force: bool = False) -> ProfileEntry:
        """Make a profile active and, when auto_load is on, apply its settings."""
        entry = self.get_profile(filename)
        if force or entry.auto_load:
            self._backup_live()
            self.set_active(filename)
            self._reload_ui()
        else:
            self.set_active(filename)
        return entry

    def save_active_if_enabled(self) -> bool:
        active = self.active_filename()
        if not active:
            return False
        try:
            entry = self.get_profile(active)
        except KeyError:
            return False
        if not entry.auto_save:
            return False
        self.update_from_current(active)
        return True

    def save_current_as(self, game_id: str, display_name: str) -> ProfileEntry:
        filename = self.next_filename(game_id)
        self._write_profile(filename, self._gather_values())
        self._upsert_entry(filename, game_id, display_name, preserve=False)
        return self.activate(filename, force=True)

    def create_fresh(self, game_id: str, display_name: str) -> ProfileEntry:
        filename = self.next_filename(game_id)
        self._write_profile(filename, dict(defaults()))
        self._upsert_entry(filename, game_id, display_name, preserve=False)
        return self.activate(filename, force=True)

    def update_from_current(self, filename: str) -> ProfileEntry:
        self._write_profile(filename, self._gather_values())
        meta = self._entry_meta(filename)
        self._upsert_entry(filename, meta.get("game_id", "custom"),
                           meta.get("display_name", filename[:-5]))
        return self.get_profile(filename)

    def set_profile_model(self, filename: str, source_model_path: str) -> ProfileEntry:
        if not os.path.isfile(source_model_path):
            raise FileNotFoundError(source_model_path)
        extension = os.path.splitext(source_model_path)[1] or ".onnx"
        model_file = filename[:-5] + extension
        destination = self._model_path(model_file)
        os.makedirs(self.models_dir, exist_ok=True)
        tmp = destination + ".tmp"
        shutil.copy2(source_model_path, tmp)
        os.replace(tmp, destination)
        index = self._read_index()
        entry = index["entries"].setdefault(filename, {})
        entry["model_file"] = model_file
        entry["updated"] = _utc_now()
        self._write_index(index)
        return self.get_profile(filename)

    def clear_profile_model(self, filename: str) -> ProfileEntry:
        index = self._read_index()
        entry = index["entries"].setdefault(filename, {})
        model_file = entry.get("model_file", "")
        entry["model_file"] = ""
        entry["updated"] = _utc_now()
        self._write_index(index)
        if model_file:
            path = self._model_path(model_file)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        return self.get_profile(filename)

    def delete(self, filename: str, *, fallback_filename: str | None = None) -> str:
        path = self._profile_path(filename)
        was_active = self.active_filename() == filename
        model_file = self._entry_meta(filename).get("model_file", "")
        if os.path.isfile(path):
            os.remove(path)
        index = self._read_index()
        index["entries"].pop(filename, None)
        self._write_index(index)
        if model_file:
            model_path = self._model_path(model_file)
            if os.path.isfile(model_path):
                try:
                    os.remove(model_path)
                except OSError:
                    pass
        if not was_active:
            return self.active_filename()
        remaining = [p.filename for p in self.list_profiles()]
        replacement = fallback_filename if fallback_filename in remaining else (remaining[0] if remaining else "")
        if replacement:
            self.activate(replacement, force=True)
        else:
            self.set_active("")
            self._reload_ui()
        return self.active_filename()

    def maybe_load_active_on_startup(self) -> None:
        active = self.active_filename()
        if not active:
            return
        try:
            entry = self.get_profile(active)
        except KeyError:
            return
        if entry.auto_load:
            self.activate(active, force=True)
