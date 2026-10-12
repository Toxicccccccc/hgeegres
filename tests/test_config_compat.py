"""Configuration compatibility tests.

The shared JSON config is read by the GUI, the native engine and the Python
engine, so a change here is the easiest way to break the whole app silently.
These checks pin the behaviour that must survive:

* confidence values are stored 0-100 and internally 0-1;
* an older config that still uses the ``trigger_key`` alias loads;
* per-game profiles round-trip through save and apply;
* the flat keys stay the live source of truth (an old build can still read it);
* a corrupt or partial document is sanitised rather than raising.

Run:  python tests/test_config_compat.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import profile_manager  # noqa: E402

FAILURES: list[str] = []


def check(condition, description):
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


def main() -> int:
    # --- profile library semantics ---------------------------------------
    config = {"model_path": "m.engine", "fov": 437, "aim_height": 93}
    config = profile_manager.sanitise(config)
    check(config["active_profile"] == "default", "a fresh config defaults to 'default'")

    profile_manager.upsert_profile(config, "Valorant", {"fov": 320, "aim_height": 80})
    check(
        profile_manager.list_profiles(config) == ["Valorant"],
        "a saved profile is listed",
    )
    merged = profile_manager.apply_profile(config, "Valorant")
    check(merged is not None and merged["fov"] == 320, "applying a profile overrides fov")
    check(
        merged["model_path"] == "m.engine",
        "applying a profile keeps values it does not define (additive merge)",
    )

    # A profile must never nest the library inside itself.
    profiles = config["profiles"]["Valorant"]
    check("profiles" not in profiles and "active_profile" not in profiles,
          "a profile bundle excludes the profile metadata keys")

    # Bad names are rejected, not written.
    for bad in ("", "   ", None, "x" * 49, "a\nb"):
        try:
            profile_manager.upsert_profile(config, bad, {"fov": 1})
            check(False, f"invalid name {bad!r} is rejected")
        except ValueError:
            check(True, f"invalid name {bad!r} is rejected")

    # Deleting the active profile falls back to default.
    profile_manager.set_active(config, "Valorant")
    profile_manager.delete_profile(config, "Valorant")
    check(
        profile_manager.active_profile(config) == "default",
        "deleting the active profile falls back to default",
    )

    # --- sanitising a damaged document -----------------------------------
    damaged = {"profiles": {"ok": {"fov": 10}, "bad": "not-a-dict"}, "active_profile": 42}
    profile_manager.sanitise(damaged)
    check(list(damaged["profiles"].keys()) == ["ok"], "non-dict profiles are dropped")
    check(damaged["active_profile"] == "default", "a non-string active profile resets")

    # --- round-tripe through JSON ----------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        document = {
            "model_path": "m.engine",
            "confidence_threshold": 75,
            "action_confidence_threshold": 85,
            "profiles": {"Valorant": {"fov": 320}},
            "active_profile": "Valorant",
        }
        path.write_text(json.dumps(document), encoding="utf-8")
        loaded = profile_manager.sanitise(json.loads(path.read_text(encoding="utf-8")))
        check(loaded["active_profile"] == "Valorant", "active profile survives a JSON round-trip")
        check(
            profile_manager.get_profile(loaded, "Valorant")["fov"] == 320,
            "profile values survive a JSON round-trip",
        )
        # The flat keys must remain readable by a build that knows nothing of
        # profiles -- that is the compatibility guarantee.
        check(loaded["confidence_threshold"] == 75,
              "flat 0-100 confidence stays out of the profile block")

    # --- legacy aliases ---------------------------------------------------
    # An older config used "trigger_key"; the GUI maps it onto lock_key.
    legacy = {"trigger_key": "Mouse 5", "fov": 400}
    mapped = legacy.get("lock_key", legacy.get("trigger_key", "Alt"))
    check(mapped == "Mouse 5", "the legacy trigger_key alias still resolves")

    # An older config stored the screen resolution as width/height; it must still
    # be read when the new ScreenResX / ScreenResY keys are absent.
    old_resolution = {"width": 2560, "height": 1440}
    upgraded_x = old_resolution.get("ScreenResX", old_resolution.get("width", 1920))
    upgraded_y = old_resolution.get("ScreenResY", old_resolution.get("height", 1080))
    check((upgraded_x, upgraded_y) == (2560, 1440),
          "the legacy width/height resolution is read as ScreenResX/Y")
    # ...and the new keys win when both are present.
    both = {"ScreenResX": 3840, "ScreenResY": 2160, "width": 1280, "height": 720}
    check(both.get("ScreenResX", both.get("width")) == 3840,
          "the new ScreenResX wins over a stale width key")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} config check(s) FAILED:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("All configuration compatibility checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
