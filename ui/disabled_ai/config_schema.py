"""Declarative schema for the DisabledAssistance config, Lunar V3 layout.

Field types understood by ``lunar_v3.widgets.FieldRow``:
    float, int      -> gradient slider with an animated value chip
    inttext, string -> line edit
    bool            -> round purple checkbox (or ToggleSwitch where noted)
    choice          -> combobox
    keybind         -> click-to-bind button that records the pressed key's VK code
    model           -> combobox listing the models/ folder (fills model_path)
    color           -> clickable swatch that opens a colour picker (hex string)

A field may carry a ``goal`` string: it is shown as the control's tooltip and
explains what the number is *for*, not just what it is. ``visible_when`` +
``visible_for`` hide a field until another control selects a matching value.
"""

import os
from pathlib import Path

# Windows virtual-key codes for the keybind picker.
KEYBIND_OPTIONS = [
    ("Left Mouse",   0x01),
    ("Right Mouse",  0x02),
    ("Middle Mouse", 0x04),
    ("Mouse 4 (X1)", 0x05),
    ("Mouse 5 (X2)", 0x06),
    ("Shift",        0x10),
    ("Ctrl",         0x11),
    ("Alt",          0x12),
    ("Caps Lock",    0x14),
    ("Tab",          0x09),
    ("Space",        0x20),
    ("E",            0x45),
    ("Q",            0x51),
    ("F",            0x46),
    ("C",            0x43),
    ("V",            0x56),
    ("X",            0x58),
    ("Z",            0x5A),
    ("R",            0x52),
    ("T",            0x54),
    ("G",            0x47),
    ("B",            0x42),
    ("F1",           0x70),
    ("F2",           0x71),
]

KEYBIND_NAME_TO_CODE = {name.lower(): code for name, code in KEYBIND_OPTIONS}
KEYBIND_CODE_TO_NAME = {code: name for name, code in KEYBIND_OPTIONS}

# Friendly names for the virtual-key codes a click-to-capture keybind can produce
# but that are not in the short KEYBIND_OPTIONS list. Without this, capturing a
# key such as Enter or a digit would show a bare "0x0D" and look unmapped even
# though the engine reads it fine.
KEYBIND_EXTRA_NAMES = {
    0x08: "Backspace",
    0x0D: "Enter",
    0x1B: "Esc",
    0x21: "Page Up",
    0x22: "Page Down",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2D: "Insert",
    0x2E: "Delete",
    0x5D: "Menu",
    0x5B: "Windows",
    0x13: "Pause",
    0x2C: "Print Screen",
    0x91: "Scroll Lock",
    0xA0: "Left Shift",
    0xA1: "Right Shift",
    0xA2: "Left Ctrl",
    0xA3: "Right Ctrl",
    0xA4: "Left Alt",
    0xA5: "Right Alt",
}


def keybind_display_name(code: int | str | None) -> str:
    """Return a human name for a virtual-key code, e.g. 0x01 -> 'Left Mouse'.

    Used by the click-to-capture keybind control so a captured key always reads
    back as something meaningful, whether or not it appeared in the fixed
    KEYBIND_OPTIONS menu. Unknown codes fall back to 'Key'/'Mouse' plus the code.
    """
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "Unbound"
    name = KEYBIND_CODE_TO_NAME.get(code) or KEYBIND_EXTRA_NAMES.get(code)
    if name:
        return name
    # 0x30-0x39 are the top-row digits, 0x41-0x5A the letters.
    if 0x30 <= code <= 0x39:
        return chr(code)
    if 0x41 <= code <= 0x5A:
        return chr(code)
    if 0x60 <= code <= 0x69:
        return f"Numpad {code - 0x60}"
    if 0x01 <= code <= 0x06:
        return f"Mouse {code}"
    return f"Key 0x{code:02X}"

# Capture backends the engines actually implement. The list once offered wgc /
# mss / udp as well, but neither the native nor the Python backend honours those
# names: the native engine only knows dxgi, gdi and synthetic, so picking wgc or
# udp silently fell back to dxgi. The menu now lists exactly what works. (The
# Python MSS grabber is still reachable through the "Use MSS Grabber" toggle on
# the Python engine.)
CAPTURE_METHODS = ["dxgi", "gdi"]
CAPTURE_METHOD_GOALS = {
    "dxgi": "Desktop Duplication — lowest latency on a full-screen game.",
    "gdi": "GDI BitBlt — software fallback; highest latency, widest compatibility.",
}

INPUT_OPTIONS = ["Auto", "Left mouse", "Right mouse", "Hold", "Toggle"]
MOVEMENT_METHODS = ["sigmadrift", "legacy"]
TARGET_PRIORITY_MODES = ["closest", "confidence", "distance", "hybrid", "sticky"]
AIMING_CURVES = ["Linear", "Quadratic", "Cubic", "Rational"]
FOV_SHAPES = ["Square", "Circle"]

# Common desktop resolutions for the Capture page dropdown, most used first.
# The field also offers a Custom… entry that reveals width/height spinboxes, so
# any size (including an ultrawide or a non-native panel) can still be set.
RESOLUTION_PRESETS = [
    (1920, 1080),   # 1080p
    (2560, 1440),   # 1440p
    (3840, 2160),   # 4K UHD
    (1280, 720),    # 720p
    (1600, 900),    # 900p
    (1366, 768),    # common laptop
    (2560, 1080),   # ultrawide 21:9
    (3440, 1440),   # ultrawide QHD
]

BOOL_VISIBLE_ON = ["True"]

# Folders searched for selectable models. The project ships weights under
# models/, so the model dropdown lists what is actually on disk instead of
# making the user paste an absolute path.
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
MODEL_EXTENSIONS = (".engine", ".pt", ".onnx")


def list_models(models_dir: Path | str | None = None) -> list[str]:
    """Return every model weight found under ``models/`` as absolute paths.

    Sorted with the native ``.engine`` files first (fastest path), then the
    others, each group alphabetical, so the dropdown leads with the models that
    give the best frame rate.
    """
    directory = Path(models_dir) if models_dir else MODELS_DIR
    if not directory.is_dir():
        return []
    found: list[str] = []
    try:
        for name in os.listdir(directory):
            path = directory / name
            if path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS:
                found.append(str(path))
    except OSError:
        return []
    found.sort(key=lambda p: (Path(p).suffix.lower() != ".engine", Path(p).name.lower()))
    return found


def F(key, label, type, default, **kw):
    field = dict(key=key, label=label, type=type, default=default)
    field.update(kw)
    return field


SCHEMA = {
    "Dashboard": [],

    "Aim": [
        {
            "title": "Search Area",
            "subtitle": "How much of the game image is searched for targets.",
            "fields": [
                F("fov", "FOV / Capture Size", "int", 609, min=100, max=1280, step=1,
                  goal="Size of the square searched around the crosshair. Increase it if "
                       "visible targets are reported outside the FOV; a larger area can "
                       "make small targets harder to detect.",
                  simple=True, simple_label="Search area (pixels)"),
            ],
        },
        {
            "title": "Targeting",
            "subtitle": "How a target is chosen and how stubbornly it is held.",
            "fields": [
                F("lock_smoothness", "Lock Smoothness", "float", 1.0, min=1.0, max=10.0, step=0.1, decimals=1,
                  goal="How quickly the crosshair closes the remaining gap while you hold Lock. "
                       "1.0 moves the full correction; higher values move more gently. "
                       "Works with every lock mode.",
                  simple=True, simple_label="Lock smoothness"),
                F("aim_height", "Aim Height", "int", 93, min=0, max=100,
                  goal="Choose where to aim in the detected target: 100 is the top, 0 is the feet.",
                  simple=True, simple_label="Aim point"),
                F("smoothness", "Smoothness", "float", 1.0, min=1.0, max=20.0, step=0.1, decimals=1,
                  goal="How much of the remaining distance to correct each frame. 1.0 moves "
                       "the crosshair all the way onto the target (recommended); higher "
                       "values make movement gentler and slower.",
                  simple=True, simple_label="Movement response"),
                F("aiming_curve", "Aiming Curve", "choice", "Linear", choices=AIMING_CURVES,
                  goal="Shape of the approach: Linear is constant, Rational eases in hardest."),
                F("hard_lock", "Hard Lock", "bool", True,
                  goal="Use a direct correction from the current detection rather than a "
                       "lagging movement trajectory. Lock smoothness still controls how "
                       "much of the remaining gap is applied each update."),
                F("movement_method", "Movement Method", "choice", "legacy", choices=MOVEMENT_METHODS,
                  goal="Only used when Hard Lock is off. sigmadrift = human-like trajectory "
                       "model; legacy = direct per-frame correction.",
                  visible_for=["False"], visible_when="hard_lock"),
                F("sigmadrift_snap", "Lock Speed", "int", 100, min=0, max=100, step=5,
                  goal="How fast the crosshair closes on the target when Hard Lock is off. "
                       "Higher snaps on almost instantly; lower keeps a slower, more human arc.",
                  visible_when="movement_method", visible_for=["sigmadrift"]),
                F("recoil_compensation", "Recoil Compensation", "bool", True,
                  goal="Keep the aim on the head while spraying by pulling the crosshair "
                       "back down against weapon kick. Turn off if you want the aim to "
                       "ride the recoil naturally."),
                F("recoil_strength", "Recoil Compensation Strength", "int", 65, min=0, max=100, step=5,
                  goal="How hard to fight the recoil. Higher holds the head harder during a "
                       "full spray; lower allows more natural rise.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="recoil_compensation"),
                F("prediction_enabled", "Enable Prediction", "bool", True,
                  goal="Lead a moving target to compensate for pipeline latency. Keep on for "
                       "a running target."),
                F("prediction_horizon_ms", "Prediction Horizon (ms)", "int", 20, min=0, max=400, step=5,
                  goal="How far ahead to lead, in milliseconds. 20 covers the pipeline delay "
                       "without overshooting a strafing target.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="prediction_enabled"),
            ],
        },
        {
            "title": "Target Selection",
            "subtitle": "Priority and re-acquisition behaviour.",
            "fields": [
                F("target_priority_mode", "Priority Mode", "choice", "closest",
                  choices=TARGET_PRIORITY_MODES,
                  goal="Which detection wins when no target is locked yet. 'closest' "
                       "picks the one nearest your crosshair."),
                F("target_stickiness", "Stickiness", "int", 2, min=0, max=4,
                  goal="Only used if Focus Single Target is off: how strongly to resist "
                       "switching to a rival."),
                F("focus_single_target", "Focus Single Target", "bool", True,
                  goal="Lock ONE target and keep following it -- it will not swap to a "
                       "different enemy until the current one is gone.",
                  simple=True, simple_label="Stay on one target"),
                F("reacquire_radius_px", "Re-acquire Radius (px)", "int", 120, min=0, max=600, step=4,
                  goal="A new box within this radius of the last one counts as the same target."),
                F("target_lost_grace_ms", "Target Lost Grace (ms)", "int", 250, min=0, max=2000, step=10,
                  goal="How long a lost target is remembered before re-acquisition."),
            ],
        },
        {
            "title": "Kalman Filter — Movement Prediction",
            "subtitle": "Smoothing filter for target position prediction: smooth aiming without jitter.",
            "fields": [
                F("kalman_enabled", "Enable Kalman Filter", "bool", True,
                  goal="Smooth the tracked target position and learn its velocity so the crosshair "
                       "never jitters and keeps following when a detection briefly drops out."),
                F("kalman_process_noise", "Process Noise", "float", 40.0, min=1.0, max=2000.0, step=1.0, decimals=1,
                  goal="How much the filter expects the target to accelerate on its own. Higher = "
                       "reacts faster to sudden movement changes but smooths less.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="kalman_enabled"),
                F("kalman_measurement_noise", "Measurement Noise", "float", 35.0, min=1.0, max=2000.0, step=1.0, decimals=1,
                  goal="How much you distrust each detection box. Raise it if boxes wobble frame to "
                       "frame (sensor/camera error); lower it to follow detections more quickly.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="kalman_enabled"),
                F("kalman_speed_multiplier_x", "Speed Multiplier X", "float", 1.0, min=0.1, max=3.0, step=0.05, decimals=2,
                  goal="Scales the filter's horizontal velocity. Above 1 leads further left/right; "
                       "below 1 is calmer on the X axis.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="kalman_enabled"),
                F("kalman_speed_multiplier_y", "Speed Multiplier Y", "float", 1.0, min=0.1, max=3.0, step=0.05, decimals=2,
                  goal="Scales the filter's vertical velocity. Keep near 1 for most games; raise it "
                       "if a fast-falling target is under-led.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="kalman_enabled"),
                F("kalman_reset_threshold", "Reset Threshold", "float", 400.0, min=0.0, max=2000.0, step=10.0, decimals=0,
                  goal="Filter reinitialization threshold. If a new measurement lands further than "
                       "this many pixels from the estimate, the filter restarts instead of "
                       "smearing across a target switch. 0 disables the check.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="kalman_enabled"),
            ],
        },
        {
            "title": "Movement Shaping (Accessibility)",
            "subtitle": "Bounds every step so the crosshair stays controllable.",
            "fields": [
                F("movement_smoothing_enabled", "Enable Movement Shaping", "bool", True,
                  goal="Cap the per-frame step and ease in/out. Turn off for raw movement."),
                F("movement_max_step_px", "Max Step (px)", "float", 60.0, min=1.0, max=400.0, step=1.0, decimals=0,
                  goal="Largest movement allowed in a single frame.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="movement_smoothing_enabled"),
                F("movement_acceleration", "Acceleration (%)", "int", 35, min=1, max=100, step=1,
                  goal="Fraction of the remaining speed gained per frame. Lower is gentler.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="movement_smoothing_enabled"),
                F("movement_stop_tolerance_px", "Stop Tolerance (px)", "float", 2.0, min=0.0, max=32.0, step=0.5, decimals=1,
                  goal="Within this distance the aim snaps and settles, killing oscillation.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="movement_smoothing_enabled"),
            ],
        },
    ],

    "Detection": [
        {
            "title": "Confidence & Suppression",
            "subtitle": "The two thresholds that decide what counts as a target.",
            "fields": [
                F("confidence_threshold", "Confidence Threshold", "float", 0.40, min=0.0, max=1.0, step=0.01, decimals=2,
                  goal="Goal: the minimum score a box must reach to be considered at all. "
                       "Lower it (0.25-0.40) if real targets are being missed; raise it if "
                       "background clutter is being detected."),
                F("action_confidence_threshold", "Action Confidence", "float", 0.60, min=0.0, max=1.0, step=0.01, decimals=2,
                  goal="Goal: the higher bar a target must clear before the engine is allowed "
                       "to move or click. Keep it above Confidence Threshold so weak boxes can "
                       "be tracked but never acted on."),
                F("iou_threshold", "IoU Threshold (NMS)", "float", 0.45, min=0.0, max=1.0, step=0.01, decimals=2,
                  goal="Goal: Non-Maximum Suppression overlap. When two boxes overlap by more "
                       "than this, the weaker one is dropped. Higher = keep more overlapping "
                       "boxes (better for crowds, more doubles); lower = merge aggressively "
                       "(cleaner, may hide two players standing together)."),
            ],
        },
        {
            "title": "Capture Region",
            "subtitle": "Adjust the capture centre and the area shape.",
            "fields": [
                F("fov_shape", "FOV Shape", "choice", "Circle", choices=FOV_SHAPES,
                  goal="Circle discards detections outside a centred circle, hiding corner clutter."),
                F("offset_x", "Offset X (px)", "int", 0, min=-960, max=960, step=1,
                  goal="Shift the capture square horizontally from screen centre."),
                F("offset_y", "Offset Y (px)", "int", 0, min=-540, max=540, step=1,
                  goal="Shift the capture square vertically from screen centre."),
                F("detection_limit", "Max Detections", "int", 5, min=1, max=512, step=1,
                  goal="Cap on boxes processed per frame."),
            ],
        },
        {
            "title": "Preprocessing",
            "fields": [
                F("allow_duplicate_frames", "Allow Duplicate Frames", "bool", False,
                  goal="Re-run detection on unchanged pixels for a higher reported FPS. "
                       "Turn off if the preview looks frozen."),
            ],
        },
    ],

    "Triggerbot": [
        {
            "title": "Triggerbot",
            "fields": [
                F("shoot_input", "Shoot Input", "choice", "Auto", choices=INPUT_OPTIONS,
                  goal="What counts as 'fire' for the triggerbot."),
            ],
        },
    ],

    "Capture": [
        {
            "title": "Capture Method",
            "subtitle": "How frames are grabbed from the screen.",
            "fields": [
                F("capture_backend", "Capture Method", "choice", "dxgi", choices=CAPTURE_METHODS,
                  goal="dxgi is the fastest GPU path and the default; gdi is the software "
                       "fallback for machines where duplication is unavailable."),
                F("use_mss", "Use MSS Grabber", "bool", False,
                  goal="Route capture through the Python MSS grabber instead of the native "
                       "backend. Many users report cleaner, more consistent frames (and so "
                       "better detections) for small FOVs. Requires the Python engine backend."),
            ],
        },
        {
            "title": "Frame Handling",
            "fields": [
                F("resolution", "Screen Resolution", "resolution", (2560, 1440),
                  presets=RESOLUTION_PRESETS,
                  keys=("screen_res_x", "screen_res_y"),
                  goal="Your desktop size. The capture square is centred on this, "
                       "so pick the resolution your game runs at. Choose Custom "
                       "resolution… to type an exact width and height."),
                F("inference_only_when_aiming", "Infer Only While Lock Is Held", "bool", False,
                  goal="Pause model inference while the Lock key is released. The visible preview and capture can still run; detections resume as soon as you hold Lock."),
                F("detection_fps_limit", "Detection FPS Limit", "int", 0, min=0, max=1000, step=5,
                  goal="Cap how many detections run per second. 0 = unlimited (fastest, "
                       "recommended). Set a limit only if you want to lower GPU load; "
                       "the engine always runs at maximum speed when this is 0."),
            ],
        },
    ],

    "Input & Device": [
        {
            "title": "Output Device",
            "fields": [
                F("input_backend", "Input Backend", "choice", "arduino", choices=["arduino", "simulated"],
                  goal="arduino = serial hardware (no software mouse flags); simulated = dry run."),
                F("port", "COM Port", "string", "COM6",
                  goal="Serial port of the output device. Leave blank to auto-detect."),
                F("arduino_spoof", "Spoof As Basic Mouse", "bool", False,
                  goal="Tell the Arduino to present itself as a plain, generic 3-button "
                       "mouse instead of a gaming device. Use this if Windows or a game "
                       "mislabels your board, or if a device list looks suspicious. Turn it "
                       "off if your side buttons stop working."),
                F("spoof_vendor_id", "Spoof Vendor ID", "inttext", 0x046D, min=0, max=65535,
                  goal="USB vendor ID the board reports when spoofing is on. 0x046D is a "
                       "generic Logitech-style mouse.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="arduino_spoof"),
                F("spoof_product_id", "Spoof Product ID", "inttext", 0xC077, min=0, max=65535,
                  goal="USB product ID the board reports when spoofing is on.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="arduino_spoof"),
            ],
        },
        {
            "title": "Device Identity",
            "subtitle": "How the board names itself to Windows.",
            "fields": [
                F("device_name", "Device Name", "string", "",
                  goal="Optional. What you want the device to appear as in Windows. Leave "
                       "blank to keep the board's own name."),
            ],
        },
        {
            "title": "Keybinds",
            "fields": [
                F("lock_key", "Lock Key", "keybind", 0x12,
                  goal="Hold this key or mouse button to aim at the chosen target."),
            ],
        },
    ],

    "Overlay": [
        {
            "title": "Live Detection Preview",
            "subtitle": "Preview processing stays off the interface thread.",
            "fields": [
                F("floating_preview", "Show Floating Preview", "bool", True,
                  goal="Open the always-on-top window that mirrors the captured FOV."),
                F("always_on_top", "Keep Preview On Top", "bool", True,
                  goal="Pin the preview above other windows."),
                F("preview_overlay", "Draw Boxes On Preview", "bool", True,
                  goal="Draw each detection and its confidence on the preview image."),
                F("preview_show_confidence", "Show Confidence", "bool", True,
                  goal="Display each detection's model score on the visible preview."),
                F("preview_show_distance", "Show Distance", "bool", True,
                  goal="Display each detection's pixel distance from the capture crosshair."),
                F("preview_head_box", "Draw Head Box", "bool", True,
                  goal="Draw a small box on each target's head so you can see where aim will land."),
                F("preview_distance_line", "Draw Line To Crosshair", "bool", True,
                  goal="Draw a line from the crosshair to each detection so you see how far it is."),
                F("preview_crosshair_style", "Crosshair Style", "choice", "Cross",
                  choices=["Cross", "Dot", "Circle", "Cross + Dot"],
                  goal="Choose the visible marker used to show the centre of the captured image."),
                F("preview_crosshair_color", "Crosshair Colour", "color", "#FFFFFF",
                  goal="Set a high-contrast colour for the preview crosshair."),
                F("preview_crosshair_size", "Crosshair Size (px)", "int", 12, min=4, max=48, step=2,
                  goal="Set the size of the crosshair marker."),
                F("preview_rainbow", "Rainbow Preview", "bool", False,
                  goal="Cycle visible preview annotation colours. This affects only the preview."),
                F("preview_fps", "Preview Rate (fps)", "int", 20, min=2, max=60, step=1,
                  goal="Frames streamed to the preview per second, independent of detection speed."),
                F("preview_size", "Preview Resolution (px)", "int", 480, min=96, max=720, step=16,
                  goal="Pixel size of the streamed preview square."),
            ],
        },
        {
            "title": "FOV Guide",
            "fields": [
                F("show_fov", "Show FOV Guide", "bool", True,
                  goal="Draw the capture square/circle on the screen overlay."),
                F("fov_color", "FOV Colour", "color", "#2F4BFF",
                  goal="Click the swatch to pick the colour of the FOV guide."),
            ],
        },
    ],

    "Advanced": [
        {
            "title": "Diagnostics",
            "fields": [
                F("telemetry_csv_enabled", "Pipeline CSV Telemetry", "bool", False,
                  goal="Write per-frame stage timings to logs/ for profiling."),
                F("idle_backoff_enabled", "Idle Back-off", "bool", False,
                  goal="Hold a low frame rate when the screen is empty, to save GPU time."),
                F("idle_fps_floor", "Idle FPS Floor", "int", 20, min=1, max=144, step=1,
                  goal="Frame rate held while nothing is detected.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="idle_backoff_enabled"),
                F("dataset_enabled", "Dataset Collection", "bool", False,
                  goal="Save labelled frames for later model retraining."),
                F("dataset_dir", "Dataset Folder", "string", "dataset",
                  goal="Where collected frames are written.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="dataset_enabled"),
                # No baked-in choice list: the model dropdown is filled from the
                # models/ folder when the field is built (see
                # widgets.FieldRow._build_model), so a weight dropped into the
                # folder shows up without editing any code or restarting to a
                # frozen list. The key is left empty here on purpose.
                F("model_path", "Model", "model", "",
                  goal="Which detector to run. The dropdown lists the weights found "
                       "in models/; .engine is the native path and gives the best FPS. "
                       "Pick 'Custom path…' to browse for a file elsewhere."),
            ],
        },
    ],

    "Console": [],
}


def all_fields():
    """Flat iterator over every field dict, in tab order."""
    for tab, cards in SCHEMA.items():
        for card in cards:
            for field in card["fields"]:
                yield tab, card["title"], field


def defaults():
    return {f["key"]: f["default"] for _, _, f in all_fields()}


# Maps a schema key to the key the engine actually reads, for the keys that
# differ from the flat config file. Everything else is written as-is.
ENGINE_KEY_ALIASES = {
    "iou_threshold": "iou_threshold",
    "use_mss": "use_mss",
    "screen_res_x": "ScreenResX",
    "screen_res_y": "ScreenResY",
}
