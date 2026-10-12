"""Per-game assist profiles for DisabledAssistance.

A profile is a named bundle of detection/response settings that can be switched
the moment a player changes game, without re-tuning every slider by hand. The
design keeps the single source of truth in ``disabledassistance_config.json``:

    {
      "active_profile": "default",
      "profiles": {
        "default":  { <full settings dict> },
        "Valorant": { <full settings dict> }
      },
      ...
    }

Rules that make this safe to rely on:

* **The flat keys always win for the live engine.** ``profiles`` is a library,
  not a second config. Loading a profile copies its values onto the flat keys,
  so the existing engine, native backend and telemetry keep reading exactly the
  keys they already understand. Nothing downstream needs to know profiles exist.
* **A profile only carries the keys it defines.** Applying one merges over the
  current settings, so a profile saved before a new option existed simply
  inherits the current value instead of resetting it.
* **Profiles are plain data.** ``profile_manager`` never touches Qt and never
  writes the file itself; the caller decides when to persist. That keeps it unit
  testable and keeps file I/O in one place (the GUI's ``_load_config`` /
  ``save_config``).

This module is intentionally dependency-free (standard library only).
"""
from __future__ import annotations

import re
from copy import deepcopy

# Keys that describe the profile library itself and must never be copied into a
# profile's setting bundle (otherwise applying a profile would nest the library
# inside itself).
META_KEYS = frozenset({"profiles", "active_profile"})

# A profile name is shown verbatim in the UI, so keep it to a sane, printable
# length and forbid the separators that would break the config as plain JSON
# keys in a human-edited file.
_MAX_NAME_LENGTH = 48
_INVALID_NAME = re.compile(r"[\x00-\x1f]")


def is_valid_profile_name(name) -> bool:
    """True when ``name`` can be used as a profile key."""
    if not isinstance(name, str):
        return False
    stripped = name.strip()
    if not stripped or len(stripped) > _MAX_NAME_LENGTH:
        return False
    return _INVALID_NAME.search(stripped) is None


def normalise_name(name: str) -> str:
    """Trim a display name; validation is separate so errors stay explicit."""
    return (name or "").strip()


def extract_settings(flat_values: dict) -> dict:
    """Return the subset of ``flat_values`` that belongs in a profile."""
    return {key: deepcopy(value) for key, value in flat_values.items() if key not in META_KEYS}


def list_profiles(config: dict) -> list[str]:
    """Profile names in a stable, human-friendly (case-insensitive) order."""
    profiles = config.get("profiles")
    if not isinstance(profiles, dict):
        return []
    return sorted((name for name in profiles if is_valid_profile_name(name)), key=str.lower)


def active_profile(config: dict) -> str:
    """The configured active profile, or ``"default"`` when unset/invalid."""
    name = config.get("active_profile")
    return name if is_valid_profile_name(name) else "default"


def get_profile(config: dict, name: str) -> dict | None:
    """Return a copy of a profile bundle, or ``None`` when it is absent."""
    profiles = config.get("profiles")
    if not isinstance(profiles, dict):
        return None
    bundle = profiles.get(name)
    if not isinstance(bundle, dict):
        return None
    return deepcopy(bundle)


def upsert_profile(config: dict, name: str, flat_values: dict) -> dict:
    """Create or overwrite ``name`` from the current flat settings.

    Returns ``config`` for convenient chaining. Raises ``ValueError`` on a bad
    name so the caller can surface a precise message.
    """
    name = normalise_name(name)
    if not is_valid_profile_name(name):
        raise ValueError("Enter a profile name of 1-48 characters.")
    profiles = config.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        config["profiles"] = profiles
    profiles[name] = extract_settings(flat_values)
    return config


def delete_profile(config: dict, name: str) -> bool:
    """Remove ``name``. Returns False when it did not exist or is protected.

    Deleting the active profile moves the active marker to ``"default"``; the
    caller is expected to keep at least one profile. ``"default"`` itself can
    never be deleted, so the fallback the active marker points at always exists
    in the library.
    """
    if name == "default":
        return False
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or name not in profiles:
        return False
    del profiles[name]
    if active_profile(config) == name:
        config["active_profile"] = "default"
    return True


def apply_profile(config: dict, name: str) -> dict | None:
    """Merge a profile's values over the current flat settings.

    The merge is deliberately additive: a profile saved before a new option
    existed inherits the current value for it rather than clearing it. Returns
    the merged flat settings, or ``None`` when the profile does not exist.
    """
    bundle = get_profile(config, name)
    if bundle is None:
        return None
    merged = {key: deepcopy(value) for key, value in config.items() if key not in META_KEYS}
    for key, value in bundle.items():
        if key in META_KEYS:
            continue
        merged[key] = deepcopy(value)
    return merged


def set_active(config: dict, name: str) -> bool:
    """Mark ``name`` active. Returns False when the profile is unknown."""
    if get_profile(config, name) is None:
        return False
    config["active_profile"] = name
    return True


def sanitise(config: dict) -> dict:
    """Return ``config`` with a valid ``profiles`` map and active marker.

    Used on load so a hand-edited or partially written file can never make the
    GUI raise: unknown types are dropped and a missing library is created empty.
    """
    if not isinstance(config.get("profiles"), dict):
        config["profiles"] = {}
    profiles = config["profiles"]
    for name in [key for key in profiles if not is_valid_profile_name(key)]:
        del profiles[name]
    for name, bundle in list(profiles.items()):
        if not isinstance(bundle, dict):
            del profiles[name]
            continue
        profiles[name] = extract_settings(bundle)
    if not is_valid_profile_name(config.get("active_profile")):
        config["active_profile"] = "default"
    return config
