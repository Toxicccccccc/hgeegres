"""
Declarative schema for Lunar V2's flat config.json.
"""

# Windows virtual-key codes for the keybind picker. label -> VK code.
# Controller binds use 0x10000+ (not Windows VKs) — see lunar_v2 isKeybindDown.
KEYBIND_OPTIONS = [
    ("Left Mouse",   0x01),
    ("Right Mouse",  0x02),
    ("Middle Mouse", 0x04),
    ("Mouse 4 (X1)", 0x05),
    ("Mouse 5 (X2)", 0x06),
    ("Pad LT",       0x10001),
    ("Pad RT",       0x10002),
    ("Pad LB",       0x10003),
    ("Pad RB",       0x10004),
    ("Pad A",        0x10005),
    ("Pad B",        0x10006),
    ("Pad X",        0x10007),
    ("Pad Y",        0x10008),
    ("Pad LS Click", 0x10009),
    ("Pad RS Click", 0x1000A),
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

# name (case-insensitive) -> code, for tolerating string configs like "Pad LT"
KEYBIND_NAME_TO_CODE = {name.lower(): code for name, code in KEYBIND_OPTIONS}

MOUSE_METHODS = ["rp2040", "makcu", "ch340", "win32", "vigem", "rp_controller_ch340"]
CAPTURE_METHODS = ["gdi", "dxgi"]


def F(key, label, type, default, **kw):
    d = dict(key=key, label=label, type=type, default=default)
    d.update(kw)
    return d


# Tab name -> list of card (section) dicts -> list of fields.
SCHEMA = {
    "Aim": [
        {
            "title": "Aim",
            "fields": [
                F("baseSpeed", "Base Speed", "float", 0.12, min=0.0, max=1.0, step=0.005, decimals=3,
                  tooltip="Proportional aim speed toward the target."),
                F("aimHeight", "Aim Height", "int", 70, min=0, max=100,
                  tooltip="Vertical aim point inside the box (100=top/head, 0=bottom)."),
                F("damping", "Damping", "float", 0.5, min=0.0, max=2.0, step=0.01, decimals=2,
                  tooltip="Error-derivative damping to prevent overshoot."),
                F("deadzone", "Deadzone", "float", 0.0, min=0.0, max=50.0, step=0.5, decimals=1,
                  tooltip="No movement while target error is within this many pixels."),
                F("lockSmoothing", "Lock Smoothing", "float", 0.0, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Slows aim during initial lock approach (0 = snap)."),
                F("velocityAlpha", "Velocity Smoothing", "float", 0.03, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="EMA alpha for target velocity (prediction is fixed at 1 frame for mouse)."),
                F("lockGraceFrames", "Lock Grace Frames", "int", 2, min=0, max=60,
                  tooltip="Frames to keep lock after target disappears from detections."),
            ],
        },
    ],

    "Detection": [
        {
            "title": "Model / Detection",
            "fields": [
                F("confThresh", "Confidence Threshold", "float", 0.10, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Minimum detection confidence to keep."),
                F("iouThresh", "IoU Threshold (NMS)", "float", 0.45, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Non-max-suppression overlap threshold."),
                F("fovSize", "FOV / Capture Size", "int", 256, min=64, max=1280, step=16,
                  tooltip="Square capture size in pixels centered on the crosshair."),
                F("maxDetections", "Max Detections", "int", 100, min=1, max=512,
                  tooltip="Cap on detections processed per frame."),
                F("deviceId", "Device Id", "inttext", 0, min=0, max=64,
                  tooltip="DirectML GPU index for YOLO inference."),
            ],
        },
        {
            "title": "Capture Orientation",
            "fields": [
                F("flipHorizontal", "Flip Horizontal", "bool", False,
                  tooltip="Enable if the capture is mirrored left-right."),
                F("flipVertical", "Flip Vertical", "bool", False,
                  tooltip="Enable if the capture is upside down."),
            ],
        },
    ],

    "Triggerbot": [
        {
            "title": "Triggerbot",
            "fields": [
                F("useTriggerbot", "Enable Triggerbot", "bool", False,
                  tooltip="Fire when the crosshair is on a target."),
                F("triggerbotThreshold", "Threshold", "float", 0.0, min=-5.0, max=20.0, step=0.5, decimals=1,
                  tooltip="Padding around the box for trigger (px)."),
            ],
        },
    ],

    "Capture": [
        {
            "title": "Capture",
            "fields": [
                F("captureMethod", "Capture Method", "choice", "gdi", choices=CAPTURE_METHODS,
                  tooltip="gdi (broad support) or dxgi (fast, exclusive-FS sensitive)."),
                F("allowDuplicateFrames", "Allow Duplicate Frames", "bool", False,
                  tooltip="Re-run YOLO on unchanged pixels for higher inference FPS. "
                          "Aim, lock, and mouse output only update on real desktop "
                          "presents — dup passes are detection-only.",
                  visible_for=["dxgi"], visible_when="captureMethod"),
            ],
        },
    ],

    "Input & Device": [
        {
            "title": "Mouse / Device",
            "fields": [
                F("mouseMethod", "Mouse Method", "choice", "rp2040", choices=MOUSE_METHODS,
                  tooltip="vigem = virtual Xbox 360 pad (ViGEmBus). rp_controller_ch340 = gamepad host UART."),
                F("comport", "COM Port", "string", "COM3",
                  tooltip="CH340 COM. Wire: adapter TX→board RX pad, RX→TX pad, GND. Also ch340/makcu.",
                  visible_for=["ch340", "makcu", "rp_controller_ch340"]),
                F("stickSensitivity", "Stick Sensitivity", "float", 50.0, min=1.0, max=200.0, step=1.0, decimals=0,
                  tooltip="Right-stick gain for vigem / rp_controller_ch340 (50 = baseline).",
                  visible_for=["vigem", "rp_controller_ch340"]),
            ],
        },
        {
            "title": "Keybinds",
            "fields": [
                F("keybind", "Primary Keybind", "keybind", 0x02,
                  tooltip="Hold to aim. For vigem / rp_controller_ch340 use Pad LT/LB/etc."),
                F("useSecondaryKeybind", "Use Secondary Keybind", "bool", False,
                  tooltip="Enable a second activation key."),
                F("secondaryKeybind", "Secondary Keybind", "keybind", 0x01,
                  tooltip="Second activation key (mouse or Pad *)."),
            ],
        },
    ],

    "Debug": [
        {
            "title": "Debug",
            "fields": [
                F("debugSaveScreenshots", "Save Debug Screenshots", "bool", False,
                  tooltip="Write capture frames with drawn detections to disk."),
                F("debugScreenshotInterval", "Screenshot Interval", "int", 30, min=1, max=5000,
                  tooltip="Save every N frames."),
            ],
        },
    ],
}


def all_fields():
    """Flat iterator over every field dict in tab order."""
    for tab, cards in SCHEMA.items():
        for card in cards:
            for field in card["fields"]:
                yield tab, card["title"], field


def defaults():
    """Default config dict from the schema."""
    return {f["key"]: f["default"] for _, _, f in all_fields()}


def schema_key_order():
    """Schema field keys in tab/card order (for stable JSON output)."""
    return [f["key"] for _, _, f in all_fields()]
