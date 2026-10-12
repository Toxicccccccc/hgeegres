"""
Declarative schema for Inchro's flat config.json.
"""

# Windows virtual-key codes for the keybind picker. label -> VK code.
# Controller binds use 0x10000+ (not Windows VKs) — see LunarV3 isKeybindDown.
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

YOLO_OBJECTNESS = ["auto", "yes", "no"]
MOUSE_METHODS = ["rp2040", "makcu", "ch340", "win32", "kmbox", "ferrum", "kmboxNet", "titan2", "vigem", "rp_controller_ch340"]
TITAN2_MODES = ["mouse", "controller"]
CAPTURE_METHODS = ["gdi", "dxgi", "captureCard", "udp"]

# visible_when bool fields compare against these tokens (see main_window visibility)
BOOL_VISIBLE_ON = ["True"]


def F(key, label, type, default, **kw):
    d = dict(key=key, label=label, type=type, default=default)
    d.update(kw)
    return d


SCHEMA = {
    "Aim": [
        {
            "title": "Core Aim",
            "fields": [
                F("baseSpeed", "Base Speed", "float", 0.16, min=0.0, max=2.0, step=0.005, decimals=3,
                  tooltip="Proportional aim speed toward the target."),
                F("aimHeight", "Aim Height", "int", 85, min=0, max=100,
                  tooltip="Vertical aim point inside the box (100=top/head, 0=bottom)."),
                F("damping", "Damping", "float", 0.3, min=0.0, max=2.0, step=0.01, decimals=2,
                  tooltip="Anti-overshoot damping when error is shrinking."),
                F("deadzone", "Deadzone", "float", 0.0, min=0.0, max=50.0, step=0.5, decimals=1,
                  tooltip="No movement while target error is within this many pixels."),
                F("smartAimStrength", "Smart Aim Strength", "float", 0.3, min=0.0, max=5.0, step=0.01, decimals=2,
                  tooltip="Horizontal body-anchor bias from motion direction."),
                F("lockSmoothing", "Lock Smoothing", "float", 0.0, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Slow the initial lock approach (0=snap)."),
                F("aimStabilize", "Aim Stabilize", "float", 0.3, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Aim point stabilization (0=off, 1=max jitter rejection)."),
            ],
        },
        {
            "title": "Prediction",
            "fields": [
                F("predictionFrames", "Prediction Frames", "float", 1.0, min=0.0, max=20.0, step=0.5, decimals=1,
                  tooltip="How many frames ahead to lead the target."),
                F("predictionFadeinRange", "Prediction Fade-In Range", "float", 50.0, min=1.0, max=500.0, step=1.0, decimals=0,
                  tooltip="Distance (px from crosshair) over which prediction ramps from none to full."),
                F("velocityAlpha", "Velocity Smoothing", "float", 0.03, min=0.0, max=1.0, step=0.001, decimals=3,
                  tooltip="Velocity EMA blend rate for prediction."),
                F("pipelineLatency", "Pipeline Latency (ms)", "float", 0.0, min=-1.0, max=100.0, step=0.5, decimals=1,
                  tooltip="In-flight compensation delay in ms (0=off)."),
            ],
        },
        {
            "title": "Legacy Lock Matching",
            "fields": [
                F("lockGraceFrames", "Lock Grace Frames", "int", 1, min=0, max=60,
                  tooltip="Frames to hold a lock when the target briefly disappears."),
                F("lockIouMin", "Lock IoU Min", "float", 0.12, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Minimum IoU to match (lower = more lenient)."),
                F("lockMaxDistNorm", "Lock Max Dist", "float", 0.85, min=0.0, max=5.0, step=0.05, decimals=2,
                  tooltip="Max normalized center distance for lock match."),
                F("lockMaxAreaRatio", "Lock Max Area Ratio", "float", 2.5, min=1.0, max=10.0, step=0.1, decimals=1,
                  tooltip="Max size ratio change between frames."),
                F("lockHysteresisBias", "Lock Hysteresis", "float", 0.18, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Prefer current target unless a competitor scores much better."),
            ],
        },
    ],

    "Detection": [
        {
            "title": "Model / Detection",
            "fields": [
                F("confThresh", "Confidence Threshold", "float", 0.36, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Minimum detection confidence to keep."),
                F("iouThresh", "IoU Threshold (NMS)", "float", 0.25, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Non-max-suppression overlap threshold."),
                F("yoloObjectness", "YOLO Objectness", "choice", "auto", choices=YOLO_OBJECTNESS,
                  tooltip="auto: channels-first=v8+ (no obj), channels-last=v5/v7 (obj)."),
                F("fovSize", "FOV / Capture Size", "int", 256, min=50, max=1280, step=2,
                  tooltip="Square capture size in pixels centered on the crosshair."),
                F("maxDetections", "Max Detections", "int", 10, min=1, max=512,
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
        {
            "title": "Custom Tracker",
            "fields": [
                F("useCustomTracker", "Enable Custom Tracker", "bool", False,
                  tooltip="Identity tracker with color (alternative to legacy IoU sticky-lock)."),
                F("trackerUseColor", "Use Color Signature", "bool", True,
                  tooltip="Include color appearance in association.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="useCustomTracker"),
                F("trackerStickiness", "Stickiness", "float", 0.72, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Higher = harder to switch targets.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="useCustomTracker"),
                F("trackerMaxAge", "Max Age", "int", 10, min=1, max=60,
                  tooltip="Frames a confirmed target may go unmatched before drop.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="useCustomTracker"),
                F("trackerMinHits", "Min Hits", "int", 2, min=1, max=30,
                  tooltip="Consecutive frames required before a lock is allowed.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="useCustomTracker"),
                F("trackerMinConf", "Min Confidence", "float", 0.40, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Smoothed confidence required to confirm a lock.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="useCustomTracker"),
                F("trackerColorWeight", "Color Weight", "float", 0.45, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Color vs motion/size association weight.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="useCustomTracker"),
                F("trackerRatioTest", "Ratio Test", "float", 0.70, min=0.0, max=1.0, step=0.01, decimals=2,
                  tooltip="Lower = hold more when ambiguous.",
                  visible_for=BOOL_VISIBLE_ON, visible_when="useCustomTracker"),
                F("trackerMaxMatchCost", "Max Match Cost", "float", 1.80, min=0.1, max=5.0, step=0.05, decimals=2,
                  tooltip="Absolute match-quality floor (hold if worse).",
                  visible_for=BOOL_VISIBLE_ON, visible_when="useCustomTracker"),
            ],
        },
    ],

    "Triggerbot": [
        {
            "title": "Triggerbot",
            "fields": [
                F("useTriggerbot", "Enable Triggerbot", "bool", False,
                  tooltip="Fire when the crosshair is on a target."),
                F("triggerbotThreshold", "Threshold", "float", -0.5, min=-5.0, max=20.0, step=0.5, decimals=1,
                  tooltip="Padding around the box for trigger (px)."),
            ],
        },
    ],

    "Capture": [
        {
            "title": "Capture",
            "fields": [
                F("captureMethod", "Capture Method", "choice", "dxgi", choices=CAPTURE_METHODS,
                  tooltip="gdi, dxgi, captureCard (HDMI/webcam), or udp."),
                F("allowDuplicateFrames", "Allow Duplicate Frames", "bool", False,
                  tooltip="Re-run YOLO on unchanged pixels for higher inference FPS. "
                          "Mouse, velocity, prediction, lock, and scaling only update on "
                          "real desktop presents (new:) — dup: passes are detection-only."),
                F("captureDeviceIndex", "Capture Device Index", "int", 0, min=0, max=64,
                  tooltip="0-based MF device index when captureMethod is captureCard.",
                  visible_for=["captureCard"], visible_when="captureMethod"),
                F("captureDeviceName", "Capture Device Name", "string", "",
                  tooltip="Substring match on capture-card friendly name (preferred).",
                  visible_for=["captureCard"], visible_when="captureMethod"),
                F("captureWidth", "Capture Width", "int", 0, min=0, max=7680, step=1,
                  tooltip="Preferred capture width (0 = auto).",
                  visible_for=["captureCard"], visible_when="captureMethod"),
                F("captureHeight", "Capture Height", "int", 0, min=0, max=4320, step=1,
                  tooltip="Preferred capture height (0 = auto).",
                  visible_for=["captureCard"], visible_when="captureMethod"),
                F("captureFps", "Capture FPS", "int", 0, min=0, max=240, step=1,
                  tooltip="Preferred capture FPS (0 = auto).",
                  visible_for=["captureCard"], visible_when="captureMethod"),
                F("udpPort", "UDP Listen Port", "inttext", 52700, min=1, max=65535,
                  tooltip="UDP port for udp-screen-share sender frames.",
                  visible_for=["udp"], visible_when="captureMethod"),
            ],
        },
        {
            "title": "Dynamic Scaling",
            "fields": [
                F("enableScaling", "Enable Dynamic Scaling", "bool", True,
                  tooltip="Zoom in/out so targets stay roughly constant size to the detector."),
                F("scaleMin", "Min Scale (zoom-out)", "float", 0.35, min=0.1, max=1.0, step=0.05, decimals=2,
                  tooltip="Min scale = max zoom-out."),
                F("scaleTargetPx", "Target Height (px)", "int", 80, min=16, max=640, step=4,
                  tooltip="Desired target box height in net pixels."),
                F("scaleMax", "Max Scale (zoom-in)", "float", 2.0, min=1.0, max=6.0, step=0.1, decimals=1,
                  tooltip="Max zoom-in when the target is far/small."),
                F("scaleEaseSpeed", "Ease Speed", "float", 0.75, min=0.0, max=2.0, step=0.01, decimals=2,
                  tooltip="How fast scale eases toward the desired value."),
                F("scaleResetSpeed", "Reset Speed", "float", 0.25, min=0.0, max=2.0, step=0.01, decimals=2,
                  tooltip="How fast scale returns to 1.0 when there is no target."),
            ],
        },
    ],

    "Input & Device": [
        {
            "title": "Mouse / Device",
            "fields": [
                F("mouseMethod", "Mouse Method", "choice", "ch340", choices=MOUSE_METHODS,
                  tooltip="Output device for aim movement."),
                F("comport", "COM Port", "string", "",
                  tooltip="Serial port (empty = auto-detect CH340).",
                  visible_for=["ch340", "makcu", "kmbox", "ferrum", "rp_controller_ch340"]),
                F("deviceSerial", "RP2040 Serial", "string", "",
                  tooltip="16-char board id (empty = auto-pick first RP2040).",
                  visible_for=["rp2040"]),
                F("kmBaud", "KM Baud", "inttext", 115200, min=9600, max=3000000,
                  tooltip="Baud rate for kmbox / ferrum KM serial.",
                  visible_for=["kmbox", "ferrum"]),
                F("kmNetIp", "KMBox Net IP", "string", "192.168.2.188",
                  tooltip="KMBox Net device IP.",
                  visible_for=["kmboxNet"]),
                F("kmNetPort", "KMBox Net Port", "inttext", 8888, min=1, max=65535,
                  tooltip="KMBox Net UDP port.",
                  visible_for=["kmboxNet"]),
                F("kmNetMac", "KMBox Net MAC/UUID", "string", "417F0CD3",
                  tooltip="KMBox Net hex UUID.",
                  visible_for=["kmboxNet"]),
                F("titan2Mode", "Titan Two Mode", "choice", "mouse", choices=TITAN2_MODES,
                  tooltip="mouse = MKB.gpc, controller = Controller.gpc.",
                  visible_for=["titan2"]),
                F("vigemSensitivity", "Stick Sensitivity", "float", 120.0, min=1.0, max=200.0, step=1.0, decimals=0,
                  tooltip="Right-stick gain for vigem / rp_controller_ch340.",
                  visible_for=["vigem", "rp_controller_ch340"]),
            ],
        },
        {
            "title": "Keybinds",
            "fields": [
                F("keybind", "Primary Keybind", "keybind", 0x02,
                  tooltip="Hold to aim."),
                F("useSecondaryKeybind", "Use Secondary Keybind", "bool", True,
                  tooltip="Enable a second activation key."),
                F("secondaryKeybind", "Secondary Keybind", "keybind", 0x06,
                  tooltip="Second activation key."),
            ],
        },
    ],

    "Discord Overlay": [
        {
            "title": "Discord Overlay",
            "fields": [
                F("discordOverlayEnabled", "Enable Discord Overlay", "bool", False,
                  tooltip="Draw on Discord's overlay window."),
                F("overlayShowDetections", "Show Detections", "bool", False,
                  tooltip="Draw all detection boxes."),
                F("overlayShowLockedTarget", "Show Locked Target", "bool", False,
                  tooltip="Highlight the locked target."),
                F("overlayShowPredictedBox", "Show Predicted Box", "bool", False,
                  tooltip="Draw the predicted target box."),
                F("overlayShowPredictedAimPoint", "Show Predicted Aim", "bool", False,
                  tooltip="Draw the predicted aim point."),
                F("overlayShowSmartAimPoint", "Show Smart Aim", "bool", False,
                  tooltip="Draw the smart-aim / overlay-smoothed point."),
                F("overlayShowCrosshair", "Show Crosshair", "bool", False,
                  tooltip="Draw a crosshair on the overlay."),
                F("overlaySmoothSpeed", "Smooth Speed", "float", 100.0, min=0.0, max=200.0, step=0.5, decimals=1,
                  tooltip="Overlay box smoothing speed (higher = snappier)."),
            ],
        },
    ],

    "Debug": [
        {
            "title": "Debug",
            "fields": [
                F("debugSaveScreenshots", "Save Debug Screenshots", "bool", False,
                  tooltip="Write capture frames with drawn detections to disk."),
                F("debugScreenshotInterval", "Screenshot Interval", "int", 1500, min=1, max=10000,
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
