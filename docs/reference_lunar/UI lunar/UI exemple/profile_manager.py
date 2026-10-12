"""Game-specific config profiles stored under ui/configs/ with optional models in ui/models/."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from config_schema import defaults
from game_catalog import get_game

_INDEX_NAME = "_profiles.json"
_BACKUP_CONFIG = "_unload_config.json"
_BACKUP_MODEL = "_unload_best.onnx"
_BACKUP_META = "_unload_meta.json"
_RESERVED = {_INDEX_NAME, _BACKUP_CONFIG, _BACKUP_META}


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
        slug = self.game_id
        if stem == slug:
            return self.display_name
        if stem.startswith(slug) and len(stem) > len(slug):
            return f"{self.display_name} ({stem[len(slug):]})"
        return self.display_name

    @property
    def has_model(self) -> bool:
        return bool(self.model_file)


class ProfileManager:
    def __init__(
        self,
        configs_dir: str,
        models_dir: str,
        live_config_path: Callable[[], str],
        live_model_path: Callable[[], str],
        gather_values: Callable[[], dict[str, Any]],
        save_live: Callable[[dict[str, Any]], None],
        reload_ui: Callable[[], None],
    ):
        self.configs_dir = configs_dir
        self.models_dir = models_dir
        self._live_config_path = live_config_path
        self._live_model_path = live_model_path
        self._gather_values = gather_values
        self._save_live = save_live
        self._reload_ui = reload_ui
        self._index_path = os.path.join(configs_dir, _INDEX_NAME)
        os.makedirs(configs_dir, exist_ok=True)
        os.makedirs(models_dir, exist_ok=True)

    # ---- index helpers -----------------------------------------------------
    def _read_index(self) -> dict[str, Any]:
        if not os.path.isfile(self._index_path):
            return {"active": "", "entries": {}}
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                obj.setdefault("active", "")
                obj.setdefault("entries", {})
                return obj
        except (OSError, json.JSONDecodeError):
            pass
        return {"active": "", "entries": {}}

    def _write_index(self, data: dict[str, Any]) -> None:
        tmp = self._index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._index_path)

    def _entry_meta(self, filename: str) -> dict[str, Any]:
        return dict(self._read_index().get("entries", {}).get(filename, {}))

    def _upsert_entry(
        self,
        filename: str,
        game_id: str,
        display_name: str,
        *,
        preserve_settings: bool = True,
    ) -> None:
        idx = self._read_index()
        prev = idx["entries"].get(filename, {}) if preserve_settings else {}
        idx["entries"][filename] = {
            "game_id": game_id,
            "display_name": display_name,
            "updated": _utc_now(),
            "auto_save": prev.get("auto_save", True),
            "auto_load": prev.get("auto_load", True),
            "model_file": prev.get("model_file", ""),
        }
        self._write_index(idx)

    def update_profile_settings(
        self,
        filename: str,
        *,
        auto_save: bool | None = None,
        auto_load: bool | None = None,
    ) -> ProfileEntry:
        idx = self._read_index()
        entry = idx["entries"].setdefault(filename, {})
        if auto_save is not None:
            entry["auto_save"] = auto_save
        if auto_load is not None:
            entry["auto_load"] = auto_load
        entry["updated"] = _utc_now()
        self._write_index(idx)
        return self.get_profile(filename)

    def active_filename(self) -> str:
        return self._read_index().get("active", "") or ""

    def set_active(self, filename: str) -> None:
        idx = self._read_index()
        idx["active"] = filename
        self._write_index(idx)

    def get_active_profile(self) -> ProfileEntry | None:
        active = self.active_filename()
        if not active:
            return None
        try:
            return self.get_profile(active)
        except KeyError:
            return None

    # ---- paths -------------------------------------------------------------
    def _profile_path(self, filename: str) -> str:
        return os.path.join(self.configs_dir, filename)

    def _model_store_path(self, model_file: str) -> str:
        return os.path.join(self.models_dir, model_file)

    def model_filename_for_profile(self, profile_filename: str) -> str:
        return profile_filename[:-5] + ".onnx"

    def _scan_profile_files(self) -> list[str]:
        if not os.path.isdir(self.configs_dir):
            return []
        out = []
        for name in os.listdir(self.configs_dir):
            if not name.lower().endswith(".json"):
                continue
            if name in _RESERVED:
                continue
            out.append(name)
        out.sort(key=lambda n: (n.lower().removesuffix(".json"), n))
        return out

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
        updated = meta.get("updated", "")

        if not game_id:
            stem = filename[:-5]
            game_id = stem.rstrip("0123456789") or "custom"
        if not display_name:
            game = get_game(game_id)
            display_name = game.name if game else stem.replace("_", " ").title()

        return ProfileEntry(
            filename=filename,
            game_id=game_id,
            display_name=display_name,
            updated=updated,
            active=filename == active,
            auto_save=bool(meta.get("auto_save", True)),
            auto_load=bool(meta.get("auto_load", True)),
            model_file=str(meta.get("model_file", "") or ""),
        )

    def list_profiles(self) -> list[ProfileEntry]:
        idx = self._read_index()
        active = idx.get("active", "")
        entries = idx.get("entries", {})
        return [
            self._build_entry(filename, entries.get(filename, {}), active)
            for filename in self._scan_profile_files()
        ]

    def list_profiles_for_game(self, game_id: str) -> list[ProfileEntry]:
        return [p for p in self.list_profiles() if p.game_id == game_id]

    def get_profile(self, filename: str) -> ProfileEntry:
        idx = self._read_index()
        if not os.path.isfile(self._profile_path(filename)):
            raise KeyError(filename)
        return self._build_entry(filename, idx.get("entries", {}).get(filename, {}), idx.get("active", ""))

    # ---- deploy config / model to Inchro.exe folder ------------------------
    def _copy_to_live_config(self, filename: str) -> None:
        src = self._profile_path(filename)
        dst = self._live_config_path()
        if not os.path.isfile(src):
            raise FileNotFoundError(src)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        shutil.copy2(src, dst)

    def _deploy_model(self, model_file: str) -> bool:
        if not model_file:
            return False
        src = self._model_store_path(model_file)
        if not os.path.isfile(src):
            return False
        dst = self._live_model_path()
        folder = os.path.dirname(os.path.abspath(dst))
        os.makedirs(folder, exist_ok=True)

        # Ensure only one best.onnx beside Inchro.exe.
        if os.path.isfile(dst):
            os.remove(dst)
        for name in os.listdir(folder):
            lower = name.lower()
            if lower == "best.onnx" and name != os.path.basename(dst):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass

        shutil.copy2(src, dst)
        return True

    def _backup_path(self, name: str) -> str:
        return os.path.join(self.configs_dir, name)

    def _read_backup_meta(self) -> dict[str, Any]:
        path = self._backup_path(_BACKUP_META)
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            return obj if isinstance(obj, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_backup_meta(self, meta: dict[str, Any]) -> None:
        path = self._backup_path(_BACKUP_META)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, path)

    def _backup_live_state(self, *, profile_deployed_model: bool) -> None:
        """Snapshot live config/model so the user can unload back to this state."""
        live_cfg = self._live_config_path()
        cfg_backup = self._backup_path(_BACKUP_CONFIG)
        if os.path.isfile(live_cfg):
            shutil.copy2(live_cfg, cfg_backup)
        else:
            with open(cfg_backup, "w", encoding="utf-8") as f:
                json.dump(defaults(), f, indent=2)

        live_model = self._live_model_path()
        model_backup = os.path.join(self.models_dir, _BACKUP_MODEL)
        had_model = os.path.isfile(live_model)
        if had_model:
            os.makedirs(self.models_dir, exist_ok=True)
            shutil.copy2(live_model, model_backup)
        elif os.path.isfile(model_backup):
            os.remove(model_backup)

        self._write_backup_meta({
            "backed_up_at": _utc_now(),
            "had_model": had_model,
            "profile_deployed_model": profile_deployed_model,
        })

    def can_unload(self) -> bool:
        return os.path.isfile(self._backup_path(_BACKUP_CONFIG))

    def unload(self) -> bool:
        """Restore the live config/model from before the last profile load."""
        cfg_backup = self._backup_path(_BACKUP_CONFIG)
        if not os.path.isfile(cfg_backup):
            return False

        meta = self._read_backup_meta()
        shutil.copy2(cfg_backup, self._live_config_path())

        live_model = self._live_model_path()
        model_backup = os.path.join(self.models_dir, _BACKUP_MODEL)
        if meta.get("had_model") and os.path.isfile(model_backup):
            os.makedirs(os.path.dirname(os.path.abspath(live_model)), exist_ok=True)
            if os.path.isfile(live_model):
                os.remove(live_model)
            shutil.copy2(model_backup, live_model)
        elif meta.get("profile_deployed_model") and os.path.isfile(live_model):
            os.remove(live_model)

        self.set_active("")
        self._reload_ui()
        return True

    def _deploy_live_files(self, entry: ProfileEntry) -> None:
        self._copy_to_live_config(entry.filename)
        if entry.model_file:
            self._deploy_model(entry.model_file)

    def deploy_profile(self, filename: str) -> ProfileEntry:
        """Copy this profile's config.json and optional model to the live Inchro folder."""
        entry = self.get_profile(filename)
        self._backup_live_state(profile_deployed_model=bool(entry.model_file))
        self._deploy_live_files(entry)
        self.set_active(filename)
        self._reload_ui()
        return entry

    def activate(self, filename: str, *, force: bool = False) -> ProfileEntry:
        """Select a profile; deploy live files if auto_load is on (or force=True)."""
        entry = self.get_profile(filename)
        if force or entry.auto_load:
            self._backup_live_state(profile_deployed_model=bool(entry.model_file))
            self._deploy_live_files(entry)
            self.set_active(filename)
            self._reload_ui()
        else:
            self.set_active(filename)
        return entry

    def load_by_game(self, game_id: str, *, force: bool = True) -> ProfileEntry | None:
        """Load the primary profile for a game (fortnite.json, or first match)."""
        matches = self.list_profiles_for_game(game_id)
        if not matches:
            return None
        preferred = f"{game_id}.json"
        target = next((p for p in matches if p.filename == preferred), matches[0])
        return self.activate(target.filename, force=force)

    def save_active_profile_if_enabled(self) -> bool:
        """If the active profile has auto_save, mirror current UI settings into it."""
        active = self.active_filename()
        if not active:
            return False
        entry = self.get_profile(active)
        if not entry.auto_save:
            return False
        self.update_from_current(active, deploy_live=False)
        return True

    # ---- profile CRUD ------------------------------------------------------
    def save_current_as(self, game_id: str, display_name: str) -> ProfileEntry:
        filename = self.next_filename(game_id)
        values = self._gather_values()
        path = self._profile_path(filename)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(values, f, indent=2)
        os.replace(tmp, path)
        self._upsert_entry(filename, game_id, display_name, preserve_settings=False)
        return self.activate(filename, force=True)

    def create_fresh(self, game_id: str, display_name: str) -> ProfileEntry:
        filename = self.next_filename(game_id)
        path = self._profile_path(filename)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(defaults(), f, indent=2)
        os.replace(tmp, path)
        self._upsert_entry(filename, game_id, display_name, preserve_settings=False)
        return self.activate(filename, force=True)

    def update_from_current(self, filename: str, *, deploy_live: bool = True) -> ProfileEntry:
        values = self._gather_values()
        path = self._profile_path(filename)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(values, f, indent=2)
        os.replace(tmp, path)
        meta = self._entry_meta(filename)
        self._upsert_entry(
            filename,
            meta.get("game_id", "custom"),
            meta.get("display_name", filename[:-5]),
        )
        if deploy_live and self.active_filename() == filename:
            self._copy_to_live_config(filename)
        return self.get_profile(filename)

    def set_profile_model(self, filename: str, source_model_path: str) -> ProfileEntry:
        if not os.path.isfile(source_model_path):
            raise FileNotFoundError(source_model_path)
        model_file = self.model_filename_for_profile(filename)
        dest = self._model_store_path(model_file)
        os.makedirs(self.models_dir, exist_ok=True)
        tmp = dest + ".tmp"
        shutil.copy2(source_model_path, tmp)
        os.replace(tmp, dest)

        idx = self._read_index()
        entry = idx["entries"].setdefault(filename, {})
        entry["model_file"] = model_file
        entry["updated"] = _utc_now()
        self._write_index(idx)

        if self.active_filename() == filename:
            profile = self.get_profile(filename)
            if profile.auto_load:
                self._deploy_model(model_file)
        return self.get_profile(filename)

    def clear_profile_model(self, filename: str) -> ProfileEntry:
        idx = self._read_index()
        entry = idx["entries"].setdefault(filename, {})
        model_file = entry.get("model_file", "")
        entry["model_file"] = ""
        entry["updated"] = _utc_now()
        self._write_index(idx)
        if model_file:
            path = self._model_store_path(model_file)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        return self.get_profile(filename)

    def delete(self, filename: str, *, fallback_filename: str | None = None) -> str:
        path = self._profile_path(filename)
        was_active = self.active_filename() == filename
        meta = self._entry_meta(filename)
        model_file = meta.get("model_file", "")

        if os.path.isfile(path):
            os.remove(path)

        idx = self._read_index()
        idx["entries"].pop(filename, None)
        self._write_index(idx)

        if model_file:
            model_path = self._model_store_path(model_file)
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
            self.deploy_profile(active)
