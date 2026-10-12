"""Named movement presets.

A preset is a bundle of movement-related settings with a plain-language name, so
a new player can pick "Gentle" or "Precise" instead of tuning six sliders. The
individual sliders stay available for anyone who wants to fine-tune; choosing a
preset just fills them in.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MovementPreset:
    id: str
    name: str
    description: str
    values: dict


PRESETS: tuple[MovementPreset, ...] = (
    MovementPreset(
        "custom",
        "Custom",
        "Your own values. Nothing is overwritten — tune each slider yourself.",
        {},
    ),
    MovementPreset(
        "gentle",
        "Gentle",
        "Slow, soft corrections. Best for shaky hands or beginners. The aim eases "
        "toward the target and settles without overshooting.",
        {
            "smoothness": 9.0,
            "aiming_curve": "Rational",
            "movement_smoothing_enabled": True,
            "movement_max_step_px": 28.0,
            "movement_acceleration": 18,
            "movement_stop_tolerance_px": 3.0,
            "movement_method": "sigmadrift",
        },
    ),
    MovementPreset(
        "balanced",
        "Balanced",
        "The everyday default: quick enough to track a moving player, smooth "
        "enough to stay controllable.",
        {
            "smoothness": 4.0,
            "aiming_curve": "Linear",
            "movement_smoothing_enabled": True,
            "movement_max_step_px": 60.0,
            "movement_acceleration": 35,
            "movement_stop_tolerance_px": 2.0,
            "movement_method": "sigmadrift",
        },
    ),
    MovementPreset(
        "precise",
        "Precise",
        "Fine control near the target. Great for long-range single taps; the aim "
        "creeps in rather than snapping.",
        {
            "smoothness": 12.0,
            "aiming_curve": "Cubic",
            "movement_smoothing_enabled": True,
            "movement_max_step_px": 18.0,
            "movement_acceleration": 12,
            "movement_stop_tolerance_px": 1.0,
            "movement_method": "sigmadrift",
        },
    ),
    MovementPreset(
        "snappy",
        "Snappy",
        "Fast, direct corrections with the smoothing bound raised. Feels closer to "
        "a raw mouse; only use it if you have steady hands.",
        {
            "smoothness": 1.5,
            "aiming_curve": "Linear",
            "movement_smoothing_enabled": True,
            "movement_max_step_px": 140.0,
            "movement_acceleration": 70,
            "movement_stop_tolerance_px": 1.0,
            "movement_method": "legacy",
        },
    ),
    MovementPreset(
        "locked",
        "Locked On",
        "Very gentle approach with a wide settle zone. The crosshair holds on the "
        "target and refuses to jitter off it.",
        {
            "smoothness": 16.0,
            "aiming_curve": "Rational",
            "movement_smoothing_enabled": True,
            "movement_max_step_px": 40.0,
            "movement_acceleration": 22,
            "movement_stop_tolerance_px": 5.0,
            "movement_method": "sigmadrift",
        },
    ),
    MovementPreset(
        "hard_lock",
        "Hard Lock (recommended)",
        "Follows a moving target accurately: the crosshair is placed on the target "
        "every frame so it never trails behind, and prediction leads it through the "
        "pipeline delay. It holds ONE target -- the closest to your crosshair -- and "
        "does not swap to another enemy mid-lock. The smoothing filter is bypassed "
        "because it only adds lag.",
        {
            # Direct, full-strength correction: no curve shaping, no partial steps.
            "smoothness": 1.0,
            "aiming_curve": "Linear",
            "movement_method": "legacy",
            "movement_smoothing_enabled": False,
            "movement_max_step_px": 400.0,
            "movement_acceleration": 100,
            "movement_stop_tolerance_px": 0.0,
            "hard_lock": True,
            # No smoothing filter: it is the single biggest source of trailing lag.
            "kalman_enabled": False,
            # Prediction covers the capture-to-output latency so the aim leads
            # rather than lags the target.
            "prediction_enabled": True,
            "prediction_horizon_ms": 20,
            # Hold one target; follow the closest, and only re-pick once it is gone.
            "focus_single_target": True,
            "target_priority_mode": "closest",
            "target_stickiness": 4,
            "target_lost_grace_ms": 150,
            "reacquire_radius_px": 240,
            "recoil_compensation": True,
            "recoil_strength": 70,
        },
    ),
)

_BY_ID = {preset.id: preset for preset in PRESETS}


def get_preset(preset_id: str) -> MovementPreset | None:
    return _BY_ID.get(preset_id)


def preset_ids() -> list[str]:
    return [preset.id for preset in PRESETS]


def preset_names() -> list[str]:
    return ["Custom" if p.id == "custom" else p.name for p in PRESETS]
