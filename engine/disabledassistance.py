import csv
import ctypes
import json
import math
import threading
import time
import pathlib
from datetime import datetime, timezone
from collections import deque
from pathlib import Path

import cv2
import keyboard
import numpy as np
import pandas as pd
import serial
import torch
import win32con
import win32gui
import win32ui
from ultralytics import YOLO

from sigma_drift import SigmaDrift, SigmaDriftConfig

pathlib.PosixPath = pathlib.WindowsPath

ROOT_DIR = Path(__file__).resolve().parent
MODEL_PATH = ROOT_DIR / "v" / "scripts" / "bestyoloV8.pt"
INPUT_OPTIONS = [
    "Left mouse",
    "Right mouse",
    "Middle mouse",
    "Mouse 4",
    "Mouse 5",
    "Alt",
    "Ctrl",
    "Shift",
    "F",
    "Space",
    "Q",
    "Auto",
]
SPECIAL_KEY_BINDINGS = {
    "alt",
    "backspace",
    "caps lock",
    "ctrl",
    "delete",
    "down",
    "end",
    "enter",
    "esc",
    "home",
    "insert",
    "left",
    "menu",
    "page down",
    "page up",
    "pause",
    "print screen",
    "right",
    "scroll lock",
    "space",
    "shift",
    "tab",
    "up",
    "windows",
}
MOUSE_BUTTON_VK = {
    "Left mouse": 0x01,
    "Right mouse": 0x02,
    "Middle mouse": 0x04,
    "Mouse 4": 0x05,
    "Mouse 5": 0x06,
}
MOVEMENT_DEADZONE_PX = 1
ON_TARGET_TOLERANCE_PX = 2
TARGET_LOST_GRACE_SECONDS = 0.25
TARGET_PRIORITY_SWITCH_MARGIN_PX = 16

# Telemetry bounds. The loop is not frame-capped, so a naive one-row-per-frame
# log can write thousands of lines a second and grow without limit. Samples are
# rate-limited to a representative rate and the file stops at a hard cap, so a
# long session can never fill the disk.
TELEMETRY_MAX_HZ = 20
TELEMETRY_MAX_ROWS = 200_000
TELEMETRY_MAX_BYTES = 24 * 1024 * 1024

# Idle back-off. After this many consecutive frames with no accepted target the
# loop starts holding the idle frame rate, so an empty screen (desktop, menu, or
# no game running) does not burn the GPU at full speed.
IDLE_GRACE_FRAMES = 45
AIMING_CURVES = ("Linear", "Ease In", "Ease Out", "Ease In-Out", "Bezier")
# How a target is chosen, and how stubbornly the engine stays on it. The names
# are the stable values stored in the config; the GUI maps them to friendly
# labels.
TARGET_PRIORITY_MODES = ("closest", "confidence", "distance", "hybrid", "sticky")
TARGET_PRIORITY_MODE_LABELS = {
    "closest": "Centre first - nearest to the crosshair",
    "confidence": "Confidence - most certain detection",
    "distance": "Distance - largest detection (closest to you)",
    "hybrid": "Hybrid - confidence weighted by distance to centre",
    "sticky": "Sticky - hold the current target longest",
}
# A stickier mode needs a larger margin before it will give up the target it is
# already tracking, so one mode choice changes both ranking and hold strength.
TARGET_PRIORITY_MODE_STICKINESS = {
    "closest": 0.0,
    "confidence": 0.0,
    "distance": 0.0,
    "hybrid": 0.35,
    "sticky": 1.0,
}
# Multiplier applied to the user's switch margin. Switching only happens when a
# rival beats the held target by this much, which is what stops two close
# detections from fighting over the crosshair every frame.
TARGET_STICKINESS_FACTOR = {
    0: 0.0,
    1: 0.5,
    2: 1.0,
    3: 1.75,
    4: 3.0,
}
TARGET_STICKINESS_LABELS = (
    "Off - switch to the best target immediately",
    "Low - switch as soon as a clearly better target appears",
    "Balanced - a moderate margin before switching",
    "High - tolerate brief target changes",
    "Maximum - hold one target unless it is badly beaten",
)


def is_valid_input_binding(value):
    if not isinstance(value, str):
        return False
    if value in MOUSE_BUTTON_VK:
        return True
    key = value.lower()
    return (
        key in SPECIAL_KEY_BINDINGS
        or (len(key) == 1 and key.isascii() and key.isprintable())
        or (
            key.startswith("f")
            and key[1:].isdigit()
            and 1 <= int(key[1:]) <= 24
        )
    )


class DisabledAssistanceEngine:
    def __init__(
        self,
        on_status=None,
        on_detection=None,
        on_preview=None,
        on_fps=None,
        on_latency=None,
        on_pipeline_metrics=None,
    ):
        self.on_status = on_status or print
        self.on_detection = on_detection or (lambda _message: None)
        self.on_preview = on_preview or (lambda _image: None)
        self.on_fps = on_fps or (lambda _fps: None)
        self.on_latency = on_latency or (lambda _latency_ms: None)
        self.on_pipeline_metrics = on_pipeline_metrics or (lambda _metrics: None)
        self._settings_lock = threading.Lock()
        self._settings = {
            "model_path": str(MODEL_PATH),
            "fov": 320,
            "width": 1920,
            "height": 1080,
            "offset_x": 0,
            "offset_y": 0,
            "port": "COM6",
            "lock_key": "Alt",
            "shoot_input": "Left mouse",
            "aim_height": 100,
            "smoothness": 1,
            "lock_smoothness": 1.0,
            "aiming_curve": "Linear",
            # Movement generation. "sigmadrift" is the biomechanical model and the
            # default; "legacy" keeps the old per-frame distance-gain correction
            # for comparison.
            "movement_method": "sigmadrift",
            # Snap 0-100: how fast a lock closes. Recoil compensation keeps the aim
            # on the head during sustained fire.
            "sigmadrift_snap": 80.0,
            "recoil_compensation": True,
            "recoil_strength": 65.0,
            # Hard lock uses a direct detection correction instead of a lagging
            # trajectory; lock_smoothness still controls the applied step size.
            "hard_lock": False,
            "sigmadrift_target_width": 20.0,
            "sigmadrift_curvature_scale": 0.025,
            "sigmadrift_overshoot_prob": 0.15,
            "sigmadrift_ou_sigma": 1.2,
            "sigmadrift_tremor_amp_max": 0.55,
            "sigmadrift_sdn_k": 0.04,
            "sigmadrift_sample_dt_mean": 7.8,
            "prediction_enabled": False,
            "prediction_horizon_ms": 100,
            "confidence_threshold": 0.25,
            # NMS IoU overlap. 0.45 is the ultralytics default; lower merges
            # overlapping boxes more aggressively, higher keeps more of them.
            "iou_threshold": 0.45,
            "action_confidence_threshold": 0.50,
            "shot_delay_ms": 150,
            "shot_interval_ms": 250,
            "detection_limit": 5,
            "fov_shape": "Square",
            "show_fov": True,
            # Capture backend. GDI BitBlt is the default; MSS reads the same
            # desktop through its own buffering path and many users report
            # cleaner frames (and steadier detections) from it.
            "capture_backend": "gdi",
            "use_mss": False,
            # Diagnostics are opt-in: CSV logging and the idle back-off.
            "telemetry_csv_enabled": False,
            "idle_backoff_enabled": True,
            "idle_fps_floor": 20.0,
            # Optional cap on detections per second. 0 = unlimited (fastest).
            "detection_fps_limit": 0,
            "inference_only_when_aiming": False,
        }
        self.model = None
        self.device = "cpu"
        self._priority_configured = False
        self.arduino = None
        self._connected_port = None
        # Set by reset_tracking(); consumed on the next frame by the run loop so
        # the GUI never mutates tracker state owned by the inference thread.
        self._tracking_reset_requested = False
        self._capture_hwnd = None
        self._capture_window_dc = None
        self._capture_dc = None
        self._capture_memory_dc = None
        self._capture_bitmap = None
        self._capture_previous_bitmap = None
        self._capture_size = None
        # MSS grabber state. Lazily created on first use, so ``mss`` is only
        # imported when the toggle is actually on.
        self._mss_instance = None
        self._mss_monitor = None
        self._mss_size = None

    def update_settings(self, settings):
        with self._settings_lock:
            self._settings.update(settings)

    def _settings_snapshot(self):
        with self._settings_lock:
            return self._settings.copy()

    def load_model(self, model_path):
        model_path = Path(model_path).expanduser()
        if not model_path.is_file():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        if model_path.suffix.lower() not in {".pt", ".engine", ".onnx"}:
            raise ValueError(f"Unsupported model format: {model_path.suffix}")

        if not self._priority_configured:
            try:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                get_current_process = kernel32.GetCurrentProcess
                get_current_process.restype = ctypes.c_void_p
                set_priority_class = kernel32.SetPriorityClass
                set_priority_class.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
                set_priority_class.restype = ctypes.c_int
                if not set_priority_class(get_current_process(), 0x00000020):
                    raise ctypes.WinError(ctypes.get_last_error())
                self.on_status("Python process priority set to Normal")
            except OSError as exc:
                self.on_status(f"Could not set Python process priority to Normal: {exc}")
            self._priority_configured = True

        self.on_status(f"Loading model: {model_path.name}")
        self.device = 0 if torch.cuda.is_available() else "cpu"
        if self.device != "cpu":
            torch.backends.cudnn.benchmark = True
        model = YOLO(str(model_path))
        self.model = model
        device_name = (
            torch.cuda.get_device_name(self.device)
            if self.device != "cpu"
            else "CPU"
        )
        self.on_status(f"Model {model_path.name} loaded on {device_name}")
        self.warmup_model()

    def warmup_model(self):
        """Pay the one-time cold-start cost before the first real frame.

        The first ``predict`` on a fresh CUDA context costs 10-20 seconds:
        context creation, cuDNN/cuBLAS handle setup and the autotune pass all
        land on that single call. Because the run loop's first ``predict`` used
        to be that call, the engine produced no preview for that whole window
        and the GUI sat on "waiting for the engine's first frame". Running one
        throwaway inference here moves that cost into startup, where the GUI is
        already showing "Loading model...", so the first real frame is warm and
        the preview appears almost immediately.
        """
        if self.model is None:
            return
        try:
            warmup_started = time.perf_counter()
            self.on_status("Warming up model (first inference)...")
            predict_options = {}
            if self.device != "cpu":
                predict_options["quantize"] = 16
            # Warm up at the EXACT shape the run loop will use. The expensive
            # first inference is per input shape, and the loop now runs at the
            # capture size rounded to a multiple of 32, so warm on that size.
            fov = int(self._settings_snapshot().get("fov", 320))
            inference_size = max(32, int(round(fov / 32.0)) * 32)
            dummy = np.zeros((fov, fov, 3), dtype=np.uint8)
            self.model.predict(
                source=dummy,
                imgsz=inference_size,
                conf=0.25,
                device=self.device,
                verbose=False,
                **predict_options,
            )
            warmup_ms = (time.perf_counter() - warmup_started) * 1000
            self.on_status(f"Warmup complete in {warmup_ms:.0f} ms")
        except Exception as exc:
            # A failed warmup must never stop the engine; the first real frame
            # will simply pay whatever cost is left.
            self.on_status(f"Model warmup failed (first frame may be slow): {exc}")

    def _inference_size(self, model_path, fov, predict_options):
        """Return the ``imgsz`` to hand Ultralytics for this model.

        A TensorRT ``.engine`` is compiled at one fixed input shape and refuses
        any other (TensorRT raises "input size ... not equal to max model size"
        when a dynamic shape is fed to a static engine). Its baked size is read
        once and cached; the engine's own input tensor is the source of truth.

        A ``.pt`` (or ``.onnx``) is dynamic, so the capture size rounded up to a
        multiple of 32 is used. Rounding keeps the tensor dimension a legal YOLO
        stride and avoids searching a padded 640 for a much smaller FOV, which
        was the dominant cost when detections ran at a third of their old rate.
        """
        suffix = Path(str(model_path)).suffix.lower()
        if suffix == ".engine":
            cached = getattr(self, "_engine_input_size", None)
            if cached is None:
                cached = self._read_engine_input_size()
                self._engine_input_size = cached
            if cached is not None:
                return cached
            # Unknown engine shape: 640 is the export default and matches the
            # TensorRT "max model size" of the weights this project ships.
            return 640
        return max(32, int(round(fov / 32.0)) * 32)

    def _read_engine_input_size(self):
        """Return the fixed H/W a TensorRT engine was compiled for, or None.

        Ultralytics prepends a JSON metadata block to an exported ``.engine``
        that records ``imgsz``; the block sits after a little-endian u32 length
        header. Reading it directly means the correct fixed size is known before
        the first inference, so the TensorRT engine is never fed a wrong shape
        (which raises "input size ... not equal to max model size"). Any problem
        yields None and the caller falls back to the export default.
        """
        predictor = getattr(self.model, "predictor", None)
        metadata = getattr(predictor, "metadata", None)
        if isinstance(metadata, dict) and metadata.get("imgsz"):
            value = metadata["imgsz"]
            if isinstance(value, (list, tuple)) and value:
                value = value[0]
            try:
                return max(32, int(value))
            except (TypeError, ValueError):
                pass
        try:
            import struct
            path = Path(getattr(self.model, "ckpt_path", "") or "")
            if not path.is_file():
                return None
            with path.open("rb") as handle:
                header = handle.read(4)
                if len(header) != 4:
                    return None
                size = struct.unpack("<I", header)[0]
                if size <= 0 or size > 1_000_000:
                    return None
                payload = handle.read(size).decode("utf-8", "ignore")
            meta = json.loads(payload)
            value = meta.get("imgsz")
            if isinstance(value, (list, tuple)) and value:
                value = value[0]
            if value is not None:
                return max(32, int(value))
        except Exception:
            return None
        return None

    def _connect_serial(self, port):
        if self.arduino is not None and self.arduino.is_open:
            self.arduino.close()
        self.arduino = None
        self._connected_port = port

        if not port:
            self.on_status(
                "Arduino: no COM port set. Plug in the board and pick its port "
                "on the Input & Device page."
            )
            return

        try:
            # 115200 matches the firmware's SERIAL_BAUD. The old 9600 rate held
            # each 8-byte packet on the wire for ~8ms, which dominated reaction
            # time; the higher rate keeps the packet format identical.
            self.arduino = serial.Serial(port, 115200, writeTimeout=0)
            self.on_status(f"Arduino connected on {port} (115200 baud)")
        except (FileNotFoundError, PermissionError) as exc:
            # On Windows pyserial opens the port through CreateFile, and pyserial
            # wraps the OS error in a SerialException for most failures -- but a
            # missing port surfaces as FileNotFoundError / PermissionError. Catch
            # the OS errors first so a bad port name gets the friendly hint rather
            # than a raw traceback string.
            self.arduino = None
            hint = "is the board plugged in?" if isinstance(exc, FileNotFoundError) \
                else "is another program using it?"
            self.on_status(
                f"Arduino error on {port}: could not open the port ({hint}) -- "
                f"running without input output."
            )
        except (serial.SerialException, ValueError) as exc:
            # pyserial wraps the Windows CreateFile failure in a SerialException,
            # whose text is the raw "could not open port 'COM6':
            # FileNotFoundError(2, ...)" the user saw. Detect the missing-port and
            # busy cases and translate them into a plain instruction instead of
            # forwarding a traceback string, and keep the session alive either way.
            self.arduino = None
            text = str(exc)
            if "FileNotFoundError" in text or "could not open port" in text:
                detail = "the port does not exist - is the board plugged in?"
            elif "Access is denied" in text or "PermissionError" in text:
                detail = "the port is busy - close the other program using it"
            else:
                detail = text
            self.on_status(
                f"Arduino error on {port}: {detail} - running without input output."
            )
        except OSError as exc:
            self.arduino = None
            self.on_status(
                f"Arduino error on {port}: could not open the port "
                f"(is the board plugged in?) -- running without input output."
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.arduino = None
            self.on_status(f"Arduino error on {port}: {exc}")

    def send_adjustment(self, x, y, click=False):
        if self.arduino is not None and self.arduino.is_open:
            code = f"{int(x)},{int(y)},{int(bool(click))}*"
            self.arduino.write(str.encode(code))
            return True
        return False

    def release_all(self):
        """Release any held movement/click state immediately.

        Called by the GUI emergency stop and on shutdown. The firmware applies a
        zero-move packet and never holds a button across packets, so a clean
        0,0,0 packet is the correct release: it guarantees no step is left in
        flight, and the device is left with no button pressed.
        """
        try:
            self.send_adjustment(0, 0, False)
        except (OSError, ValueError) as exc:
            self.on_status(f"Input release failed: {exc}")

    def reset_tracking(self):
        """Ask the running loop to drop its current target lock.

        The loop owns its tracker state, so the request is a flag it reads on the
        next frame rather than shared mutable state touched from the GUI thread.
        """
        self._tracking_reset_requested = True

    @staticmethod
    def input_is_pressed(input_name):
        if input_name == "Auto":
            return True

        def _async_pressed(virtual_key):
            get_async_key_state = ctypes.windll.user32.GetAsyncKeyState
            get_async_key_state.argtypes = (ctypes.c_int,)
            get_async_key_state.restype = ctypes.c_short
            return bool(get_async_key_state(virtual_key) & 0x8000)

        mouse_vk = MOUSE_BUTTON_VK.get(input_name)
        if mouse_vk is not None:
            return _async_pressed(mouse_vk)
        # The GUI's keybind control stores the key as a raw Windows virtual-key
        # code (an int), and the config file keeps that int. The engine only
        # understood the string names here, so a lock/shoot key recorded on the
        # Device page never matched and the assistant never moved or clicked.
        # Accept the numeric code directly (and a numeric string, for configs the
        # native bridge round-tripped through JSON).
        if isinstance(input_name, bool):
            return False
        # Any numeric form is a raw Windows virtual-key code: the GUI keybind
        # control stores an int, but JSON round-trips can hand back a float
        # (2.0) or a numeric string, and a value that failed the int/isinstance
        # checks here used to fall through to keyboard.is_pressed() and read as
        # "never pressed", which is exactly the "lock key does nothing" report.
        # Accept int, float and numeric string alike.
        if isinstance(input_name, int):
            return _async_pressed(input_name)
        if isinstance(input_name, float):
            return _async_pressed(int(input_name))
        if isinstance(input_name, str):
            text = input_name.strip()
            if text.isdigit():
                return _async_pressed(int(text))
            # Mouse buttons as spelled by the schema/keybind list.
            schema_mouse = {
                "left mouse": 0x01,
                "right mouse": 0x02,
                "middle mouse": 0x04,
                "mouse 4 (x1)": 0x05,
                "mouse 5 (x2)": 0x06,
            }
            lowered = text.lower()
            if lowered in schema_mouse:
                return _async_pressed(schema_mouse[lowered])
        try:
            return keyboard.is_pressed(input_name)
        except (ValueError, KeyError):
            # An unmapped key name must not raise inside the capture loop (a
            # raised exception aborts the frame and, under Qt's event loop, can
            # take the whole process down). An unrecognized binding simply reads
            # as "not pressed".
            return False

    @staticmethod
    def movement_step(error, smoothness, remainder, aiming_curve="Linear"):
        if abs(error) <= MOVEMENT_DEADZONE_PX:
            return 0, 0.0
        # Smoothness is a response divisor (1 = fastest, larger = gentler).
        # Older saved configs allowed values below 1, which multiplied the
        # correction and caused the crosshair to alternate across the target.
        response = min(20.0, max(1.0, float(smoothness)))
        curve_input = min(abs(error) / 64, 1.0)
        if aiming_curve == "Linear":
            curve_output = curve_input
        elif aiming_curve == "Quadratic" or aiming_curve == "Ease In":
            # The Aim page offers "Quadratic"; the engine used to only know
            # "Ease In" and raised on anything else, so choosing a preset that
            # set Quadratic/Cubic/Rational made every frame throw and the Aim
            # section appear dead. Both names now map to the same curve and the
            # old aliases still work, so existing configs keep loading.
            curve_output = curve_input * curve_input
        elif aiming_curve == "Cubic":
            curve_output = curve_input * curve_input * curve_input
        elif aiming_curve == "Rational":
            # Steeper than Quadratic at the start, still reaching exactly 1.0.
            squared = curve_input * curve_input
            curve_output = squared / (2.0 - squared) if squared < 1.0 else 1.0
        elif aiming_curve == "Ease Out":
            curve_output = 1 - (1 - curve_input) ** 2
        elif aiming_curve == "Ease In-Out":
            curve_output = curve_input * curve_input * (3 - 2 * curve_input)
        elif aiming_curve == "Bezier":
            lower = 0.0
            upper = 1.0
            for _ in range(12):
                parameter = (lower + upper) / 2
                one_minus_parameter = 1 - parameter
                x = (
                    3 * one_minus_parameter**2 * parameter * 0.25
                    + 3 * one_minus_parameter * parameter**2 * 0.25
                    + parameter**3
                )
                if x < curve_input:
                    lower = parameter
                else:
                    upper = parameter
            parameter = (lower + upper) / 2
            one_minus_parameter = 1 - parameter
            curve_output = (
                3 * one_minus_parameter**2 * parameter * 0.1
                + 3 * one_minus_parameter * parameter**2
                + parameter**3
            )
        else:
            raise ValueError(f"Unsupported aiming curve: {aiming_curve}")
        distance_gain = 0.25 + 0.25 * curve_output
        gain = min(1.0, max(0.0, distance_gain / response))
        scaled = error * gain + remainder
        if scaled * error <= 0.0:
            return 0, 0.0
        if abs(scaled) > abs(error):
            scaled = error
        movement = int(scaled)
        return movement, scaled - movement

    @staticmethod
    def sigma_drift_from_settings(settings):
        """Build a SigmaDrift generator from the engine settings.

        Returns None when the legacy movement method is selected, so the caller
        falls back to the original per-frame correction.
        """
        if str(settings.get("movement_method", "sigmadrift")).lower() != "sigmadrift":
            return None
        config = SigmaDriftConfig()
        config.target_width = float(settings.get("sigmadrift_target_width", 20.0))
        config.curvature_scale = float(settings.get("sigmadrift_curvature_scale", 0.025))
        config.overshoot_prob = float(settings.get("sigmadrift_overshoot_prob", 0.15))
        config.ou_sigma = float(settings.get("sigmadrift_ou_sigma", 1.2))
        config.tremor_amp_max = float(settings.get("sigmadrift_tremor_amp_max", 0.55))
        config.sdn_k = float(settings.get("sigmadrift_sdn_k", 0.04))
        config.sample_dt_mean = float(settings.get("sigmadrift_sample_dt_mean", 7.8))
        # Snap (0-100) is the day-to-day control: it scales the movement time and
        # the biomechanical noise so a lock closes fast and lands cleanly.
        config.snap = max(0.0, min(1.0, float(settings.get("sigmadrift_snap", 80)) / 100.0))
        return SigmaDrift(config)

    @staticmethod
    def get_aim_point(xmin, ymin, xmax, ymax, aim_height):
        center_x = (xmin + xmax) / 2
        aim_y = ymax - (ymax - ymin) * (aim_height / 100)
        return center_x, aim_y

    @staticmethod
    def predict_aim_point(aim_point, velocity, prediction_horizon_ms):
        horizon_seconds = prediction_horizon_ms / 1000
        return (
            aim_point[0] + velocity[0] * horizon_seconds,
            aim_point[1] + velocity[1] * horizon_seconds,
        )

    @staticmethod
    def is_on_target(aim_point, center):
        return float(np.hypot(aim_point[0] - center, aim_point[1] - center)) <= (
            ON_TARGET_TOLERANCE_PX
        )

    @staticmethod
    def click_is_due(
        lock_active,
        on_target,
        lock_elapsed_ms,
        shot_delay_ms,
        shoot_active,
        last_click_at,
        now,
        shot_interval_ms,
    ):
        return (
            lock_active
            and on_target
            and lock_elapsed_ms >= shot_delay_ms
            and shoot_active
            and (
                last_click_at is None
                or (now - last_click_at) * 1000 >= shot_interval_ms
            )
        )

    @staticmethod
    def select_target_index(
        detections,
        previous_target_center,
        center_offset,
        max_match_distance=None,
    ):
        target_center_x = (detections["xmin"] + detections["xmax"]) / 2
        target_center_y = (detections["ymin"] + detections["ymax"]) / 2
        if previous_target_center is not None:
            distances_squared = (
                (target_center_x - previous_target_center[0]) ** 2
                + (target_center_y - previous_target_center[1]) ** 2
            )
        else:
            distances_squared = (
                (target_center_x - center_offset) ** 2
                + (target_center_y - center_offset) ** 2
            )
        ranked = detections.assign(_distance_squared=distances_squared)
        selected_index = ranked.sort_values(
            ["_distance_squared", "confidence"],
            ascending=[True, False],
            kind="stable",
        ).index[0]
        selected_distance = float(distances_squared.loc[selected_index]) ** 0.5
        if (
            previous_target_center is not None
            and max_match_distance is not None
            and selected_distance > max_match_distance
        ):
            return None, selected_distance
        return selected_index, selected_distance

    @staticmethod
    def prioritize_more_centered_target(
        detections,
        current_index,
        center_offset,
        fov,
    ):
        priority_index, priority_distance = DisabledAssistanceEngine.select_target_index(
            detections,
            None,
            center_offset,
        )
        current = detections.loc[current_index]
        current_center_distance = float(
            np.hypot(
                (current["xmin"] + current["xmax"]) / 2 - center_offset,
                (current["ymin"] + current["ymax"]) / 2 - center_offset,
            )
        )
        switch_margin = max(TARGET_PRIORITY_SWITCH_MARGIN_PX, fov * 0.05)
        if (
            priority_index != current_index
            and current_center_distance - priority_distance >= switch_margin
        ):
            return priority_index
        return current_index

    @staticmethod
    def rank_targets_by_mode(detections, mode, center_offset, previous_target_center=None):
        """Return the index of the best detection for the chosen priority mode.

        Mirrors select_target_by_mode in the native engine so both engines rank
        identically for the same configuration. Each mode defines one score; the
        highest score wins. Returns None for an empty frame.
        """
        if detections.empty:
            return None
        center_x = (detections["xmin"] + detections["xmax"]) / 2
        center_y = (detections["ymin"] + detections["ymax"]) / 2
        to_crosshair = np.hypot(center_x - center_offset, center_y - center_offset)
        confidence = detections["confidence"].astype(float)
        if previous_target_center is not None:
            to_previous = np.hypot(
                center_x - previous_target_center[0], center_y - previous_target_center[1]
            )
        else:
            to_previous = to_crosshair
        if mode == "confidence":
            score = confidence
        elif mode == "distance":
            # Larger box first; confidence only breaks ties.
            area = (detections["xmax"] - detections["xmin"]) * (
                detections["ymax"] - detections["ymin"]
            )
            score = area * 1e-4 + confidence * 1e-3
        elif mode == "hybrid":
            closeness = 1.0 / (1.0 + to_crosshair / max(center_offset, 1.0))
            score = confidence * (0.5 + 0.5 * closeness)
        elif mode == "sticky" and previous_target_center is not None:
            score = -to_previous - 0.25 * to_crosshair
        else:
            # "closest" and the sticky fallback before any lock: nearest centre.
            score = -to_crosshair
        return int(score.idxmax())

    @staticmethod
    def select_priority_target(
        detections,
        current_index,
        center_offset,
        fov,
        mode,
        stickiness,
        focus_single_target,
        previous_target_center,
    ):
        """Decide whether to keep the held target or switch, using the mode and
        the stickiness margin.

        The held target is only given up when the ranked best beats it by the
        margin, so two close detections cannot fight over the crosshair. When
        ``focus_single_target`` is off the engine switches as soon as the mode's
        ranking changes.
        """
        priority_index = DisabledAssistanceEngine.rank_targets_by_mode(
            detections, mode, center_offset, previous_target_center
        )
        if priority_index is None:
            return current_index
        factor = TARGET_STICKINESS_FACTOR.get(int(stickiness), 1.0)
        if factor == 0.0 or not focus_single_target:
            return priority_index
        current = detections.loc[current_index]
        priority = detections.loc[priority_index]
        current_distance = float(
            np.hypot(
                (current["xmin"] + current["xmax"]) / 2 - previous_target_center[0],
                (current["ymin"] + current["ymax"]) / 2 - previous_target_center[1],
            )
        )
        priority_distance = float(
            np.hypot(
                (priority["xmin"] + priority["xmax"]) / 2 - previous_target_center[0],
                (priority["ymin"] + priority["ymax"]) / 2 - previous_target_center[1],
            )
        )
        switch_margin = max(TARGET_PRIORITY_SWITCH_MARGIN_PX, fov * 0.05) * factor
        if (
            priority_index != current_index
            and current_distance - priority_distance >= switch_margin
        ):
            return priority_index
        return current_index

    @staticmethod
    def target_reference_is_valid(
        previous_target_center,
        last_seen_at,
        now,
        grace_seconds=TARGET_LOST_GRACE_SECONDS,
    ):
        return (
            previous_target_center is not None
            and last_seen_at is not None
            and now - last_seen_at <= grace_seconds
        )

    def _release_capture_resources(self):
        hwnd = self._capture_hwnd
        window_dc = self._capture_window_dc
        dc = self._capture_dc
        memory_dc = self._capture_memory_dc
        bitmap = self._capture_bitmap
        previous_bitmap = self._capture_previous_bitmap
        self._capture_hwnd = None
        self._capture_window_dc = None
        self._capture_dc = None
        self._capture_memory_dc = None
        self._capture_bitmap = None
        self._capture_previous_bitmap = None
        self._capture_size = None
        # Release the MSS grabber too; it holds a display handle of its own.
        if self._mss_instance is not None:
            try:
                self._mss_instance.close()
            except Exception:
                pass
            self._mss_instance = None
            self._mss_monitor = None
            self._mss_size = None

        cleanup_operations = []
        if memory_dc is not None and previous_bitmap is not None:
            cleanup_operations.append(
                ("restore selected capture bitmap", lambda: memory_dc.SelectObject(previous_bitmap))
            )
        if memory_dc is not None:
            cleanup_operations.append(("delete capture memory DC", memory_dc.DeleteDC))
        if bitmap is not None:
            cleanup_operations.append(
                ("delete capture bitmap", lambda: win32gui.DeleteObject(bitmap.GetHandle()))
            )
        if dc is not None:
            cleanup_operations.append(("delete screen capture DC", dc.DeleteDC))
        if hwnd is not None and window_dc is not None:
            cleanup_operations.append(
                ("release desktop window DC", lambda: win32gui.ReleaseDC(hwnd, window_dc))
            )
        for description, operation in cleanup_operations:
            try:
                operation()
            except Exception as exc:
                self.on_status(f"Could not {description}: {exc}")

    def _create_capture_resources(self, fov):
        try:
            self._capture_hwnd = win32gui.GetDesktopWindow()
            self._capture_window_dc = win32gui.GetWindowDC(self._capture_hwnd)
            self._capture_dc = win32ui.CreateDCFromHandle(self._capture_window_dc)
            self._capture_memory_dc = self._capture_dc.CreateCompatibleDC()
            self._capture_bitmap = win32ui.CreateBitmap()
            self._capture_bitmap.CreateCompatibleBitmap(self._capture_dc, fov, fov)
            self._capture_previous_bitmap = self._capture_memory_dc.SelectObject(
                self._capture_bitmap
            )
            self._capture_size = fov
        except Exception:
            self._release_capture_resources()
            raise

    def _mss_capture(self, fov, center_x, center_y):
        """Grab the FOV region with MSS instead of GDI BitBlt.

        MSS reads the same desktop surface through its own buffering path, which
        many users find gives cleaner frames -- and therefore steadier
        detections -- for small regional captures. Coordinates match the GDI
        path: ``center_x/center_y`` is the top-left of the fov x fov square.
        """
        import mss as _mss

        if self._mss_instance is None:
            self._mss_instance = _mss.mss()
            # Monitor 1 covers the whole virtual desktop on Windows.
            self._mss_monitor = self._mss_instance.monitors[0]
        region = {
            "left": int(center_x),
            "top": int(center_y),
            "width": int(fov),
            "height": int(fov),
        }
        shot = self._mss_instance.grab(region)
        frame = np.asarray(shot)  # BGRA, tightly packed
        if frame.shape[0] != fov or frame.shape[1] != fov:
            # A region partly off-screen comes back smaller; pad back to fov.
            padded = np.zeros((fov, fov, frame.shape[2]), dtype=np.uint8)
            height = min(fov, frame.shape[0])
            width = min(fov, frame.shape[1])
            padded[:height, :width] = frame[:height, :width]
            frame = padded
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def window_capture(self, fov, center_x, center_y):
        if bool(self._settings_snapshot().get("use_mss", False)):
            return self._mss_capture(fov, center_x, center_y)
        if self._capture_size != fov:
            self._release_capture_resources()
            self._create_capture_resources(fov)

        try:
            self._capture_memory_dc.BitBlt(
                (0, 0),
                (fov, fov),
                self._capture_dc,
                (center_x, center_y),
                win32con.SRCCOPY,
            )
            signed_ints = self._capture_bitmap.GetBitmapBits(True)
            img = np.frombuffer(signed_ints, dtype=np.uint8).reshape((fov, fov, 4))
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        except Exception:
            self._release_capture_resources()
            raise

    def run(self, stop_event):
        initial_settings = self._settings_snapshot()
        active_model_path = str(
            Path(initial_settings.get("model_path", MODEL_PATH)).expanduser()
        )
        self.load_model(active_model_path)
        failed_model_path = None
        movement_remainder_x = 0.0
        movement_remainder_y = 0.0
        lock_smoothness_remainder_x = 0.0
        lock_smoothness_remainder_y = 0.0
        # SigmaDrift replaces the legacy per-frame correction when selected. It
        # generates a whole biomechanical trajectory per acquisition, so it owns
        # the movement output while a stroke is in flight.
        sigma_drift = self.sigma_drift_from_settings(initial_settings)
        sigma_drift_active = False
        last_sent_aim_x = 0.0
        last_sent_aim_y = 0.0
        last_frame_time = time.perf_counter()
        previous_target_center = None
        previous_aim_center = None
        last_target_seen_at = None
        filtered_target_center = None
        filtered_target_velocity = (0.0, 0.0)
        previous_filter_time = None
        target_lock_started_at = None
        last_click_at = None
        frame_sequence = 0
        timing_samples = {
            name: deque(maxlen=120)
            for name in (
                "capture",
                "prepare",
                "predict",
                "transfer_decode",
                "postprocess",
                "preview",
                "detection",
                "pipeline",
            )
        }
        telemetry_file = None
        telemetry_writer = None
        # CSV telemetry is OFF unless the settings explicitly ask for it
        # ("telemetry_csv_enabled": true). It is a diagnostics tool, not
        # something a normal session should pay for: the loop is uncapped, so a
        # per-frame log runs to hundreds of thousands of lines and the file never
        # stops growing. When enabled it is sampled and hard-capped so it cannot
        # fill the disk either.
        telemetry_min_interval = 1.0 / max(TELEMETRY_MAX_HZ, 1)
        telemetry_last_write = 0.0
        telemetry_rows_written = 0
        telemetry_capped_notified = False

        try:
            telemetry_dir = ROOT_DIR / "logs"
            telemetry_path = telemetry_dir / (
                f"pipeline_metrics_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.csv"
            )
            try:
                # Use the settings snapshot taken at loop start; the per-frame
                # `settings` local is only assigned inside the loop below, so
                # referencing it here raised NameError and killed the engine the
                # instant it started.
                if not initial_settings.get("telemetry_csv_enabled", False):
                    # Default path: no file is created at all. The live figures in
                    # the GUI banner still update; only disk logging is skipped.
                    raise FileNotFoundError("pipeline CSV telemetry disabled")
                telemetry_dir.mkdir(parents=True, exist_ok=True)
                telemetry_file = telemetry_path.open(
                    "x", newline="", encoding="utf-8"
                )
                telemetry_writer = csv.DictWriter(
                    telemetry_file,
                    fieldnames=(
                        "timestamp_utc",
                        "sequence",
                        "model",
                        "device",
                        "capture_ms",
                        "prepare_ms",
                        "predict_call_ms",
                        "result_transfer_decode_ms",
                        "postprocess_ms",
                        "preview_submit_ms",
                        "capture_to_detection_ms",
                        "capture_to_preview_submit_ms",
                    ),
                )
                telemetry_writer.writeheader()
                self.on_status(f"Pipeline telemetry: {telemetry_path}")
            except FileNotFoundError:
                # Telemetry disabled by configuration; not an error.
                telemetry_file = None
                telemetry_writer = None
            except OSError as exc:
                telemetry_file = None
                telemetry_writer = None
                self.on_status(f"Could not create pipeline telemetry file: {exc}")

            # Idle detection: when nothing has been detected for a while the loop
            # should not keep hammering the GPU at full rate. This counter drives a
            # graduated back-off so an empty screen (or a menu, or the desktop)
            # costs a fraction of the resources of an active match. The first
            # detection resets it immediately, so nothing is lost when a target
            # reappears.
            idle_frames = 0
            # Preview pacing. The preview is a convenience stream, not part of
            # detection, so it is throttled to preview_fps and re-read each frame
            # so a live change takes effect without a restart.
            preview_last_at = None
            # Most recent measured capture-to-detection time, used to report the
            # true detection rate independently of the idle back-off.
            last_detection_ms = None

            while not stop_event.is_set():
                frame_started = time.perf_counter()
                settings = self._settings_snapshot()
                idle_backoff_enabled = bool(settings.get("idle_backoff_enabled", True))
                idle_fps_floor = float(settings.get("idle_fps_floor", 20.0))
                preview_fps = float(settings.get("preview_fps", 20.0))
                # Optional detection-rate cap. 0 = unlimited (the fast default).
                try:
                    detection_fps_limit = float(settings.get("detection_fps_limit", 0) or 0)
                except (TypeError, ValueError):
                    detection_fps_limit = 0.0
                # Set True by the detection stage when a target is accepted; drives
                # the idle back-off at the bottom of the loop.
                saw_target = False
                requested_model_path = str(
                    Path(settings.get("model_path", MODEL_PATH)).expanduser()
                )
                if requested_model_path == active_model_path:
                    failed_model_path = None
                if requested_model_path != active_model_path:
                    if requested_model_path == failed_model_path:
                        pass
                    else:
                        try:
                            self.load_model(requested_model_path)
                            active_model_path = requested_model_path
                            failed_model_path = None
                            movement_remainder_x = 0.0
                            movement_remainder_y = 0.0
                            lock_smoothness_remainder_x = 0.0
                            lock_smoothness_remainder_y = 0.0
                            previous_target_center = None
                            previous_aim_center = None
                            last_target_seen_at = None
                            filtered_target_center = None
                            filtered_target_velocity = (0.0, 0.0)
                            previous_filter_time = None
                            target_lock_started_at = None
                            last_click_at = None
                        except Exception as exc:
                            failed_model_path = requested_model_path
                            self.on_status(
                                f"Could not load {Path(requested_model_path).name}; "
                                f"keeping {Path(active_model_path).name}: {exc}"
                            )
                fov = settings["fov"]
                center_offset = fov / 2
                # ScreenResX / ScreenResY are the current keys; width / height are
                # accepted so an older configuration still drives the capture.
                screen_x = settings.get("ScreenResX", settings.get("width", 1920))
                screen_y = settings.get("ScreenResY", settings.get("height", 1080))
                center_x = int((screen_x / 2) - center_offset + settings["offset_x"])
                center_y = int((screen_y / 2) - center_offset + settings["offset_y"])
                port = settings["port"].strip()
                if port != self._connected_port:
                    self._connect_serial(port)

                try:
                    capture_started_at = time.perf_counter()
                    frame = self.window_capture(fov, center_x, center_y)
                    capture_completed_at = time.perf_counter()
                    capture_timestamp_utc = datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    )
                    prepare_started_at = capture_completed_at
                    # Only copy the frame for the preview when a preview is actually
                    # due. Copying the full FOV and submitting it every detected
                    # frame was pure overhead: the preview runs at preview_fps
                    # (typically 20), not at the detection rate. The native engine
                    # already decouples the two; this brings the Python path in line
                    # and removes a per-frame memcpy plus a GUI-side resize/encode
                    # from the hot loop.
                    preview_due = (
                        preview_last_at is None
                        or capture_completed_at - preview_last_at
                        >= 1.0 / max(preview_fps, 1)
                    )
                    display = frame.copy() if preview_due else None
                    lock_active_for_inference = self.input_is_pressed(settings["lock_key"])
                    inference_paused = (
                        bool(settings.get("inference_only_when_aiming", False))
                        and not lock_active_for_inference
                    )
                    predict_options = {}
                    if Path(active_model_path).suffix.lower() == ".pt" and self.device != "cpu":
                        predict_options["quantize"] = 16
                    # Pick the inference size for this model. A TensorRT .engine is
                    # baked at one fixed input shape (its "max model size"), so it
                    # must be fed exactly that or TensorRT rejects the tensor. A
                    # .pt is dynamic: run it at the capture size rounded to a
                    # multiple of 32 instead of a hard 640, so a 384px FOV is not
                    # searched as 640px (the main reason detections crawled).
                    inference_size = self._inference_size(
                        active_model_path, fov, predict_options
                    )
                    prepare_completed_at = time.perf_counter()
                    predict_started_at = prepare_completed_at
                    if inference_paused:
                        predict_completed_at = predict_started_at
                        transfer_decode_started_at = predict_completed_at
                        detections = pd.DataFrame(
                            dtype=float,
                            columns=(
                                "xmin",
                                "ymin",
                                "xmax",
                                "ymax",
                                "confidence",
                            )
                        )
                    else:
                        results = self.model.predict(
                            source=frame,
                            imgsz=inference_size,
                            conf=min(settings["confidence_threshold"], 0.25),
                            # NMS overlap: higher keeps more overlapping boxes (better
                            # for crowds, more doubles); lower merges them.
                            iou=float(settings.get("iou_threshold", 0.45)),
                            device=self.device,
                            max_det=max(100, settings["detection_limit"]),
                            verbose=False,
                            **predict_options,
                        )
                        predict_completed_at = time.perf_counter()
                        transfer_decode_started_at = predict_completed_at
                        boxes = results[0].boxes
                        if boxes is None or len(boxes) == 0:
                            detections = pd.DataFrame(
                                dtype=float,
                                columns=(
                                    "xmin",
                                    "ymin",
                                    "xmax",
                                    "ymax",
                                    "confidence",
                                )
                            )
                        else:
                            box_data = boxes.data.detach().cpu().numpy()
                            detections = pd.DataFrame(
                                box_data[:, :5],
                                columns=(
                                    "xmin",
                                    "ymin",
                                    "xmax",
                                    "ymax",
                                    "confidence",
                                ),
                            )
                    transfer_decode_completed_at = time.perf_counter()
                    captured_detection_count = len(detections)

                    if settings["fov_shape"] == "Circle" and not detections.empty:
                        detection_center_x = (detections["xmin"] + detections["xmax"]) / 2
                        detection_center_y = (detections["ymin"] + detections["ymax"]) / 2
                        in_circle = (
                            (detection_center_x - center_offset) ** 2
                            + (detection_center_y - center_offset) ** 2
                            <= center_offset**2
                        )
                        detections = detections.loc[in_circle]

                    selection_time = time.perf_counter()
                    # The lock key is a plain hold: active only while the bound key
                    # or mouse button is down.
                    lock_active = self.input_is_pressed(settings["lock_key"])
                    shoot_active = self.input_is_pressed(settings["shoot_input"])
                    if self._tracking_reset_requested:
                        # Honour a GUI request to abandon the current target. Reset
                        # the whole tracker surface so the next frame re-acquires
                        # cleanly instead of resuming the old estimate.
                        self._tracking_reset_requested = False
                        previous_target_center = None
                        previous_aim_center = None
                        last_target_seen_at = None
                        filtered_target_center = None
                        filtered_target_velocity = (0.0, 0.0)
                        previous_filter_time = None
                        target_lock_started_at = None
                        lock_smoothness_remainder_x = 0.0
                        lock_smoothness_remainder_y = 0.0
                        self.on_status("Tracking state cleared.")
                    # While the lock key is HELD the target must be kept -- that is
                    # the point of holding it. This used to be 0 while locked, which
                    # means "expire unless seen within 0 seconds" (always false), so
                    # the target reference was wiped every frame and the aim re-picked
                    # a box from scratch each frame, visibly jumping between enemies.
                    # A held lock now keeps the same target for a full second even if
                    # it is briefly occluded, so it re-locks onto it on reappearance.
                    reacquire_grace = (
                        1.0
                        if lock_active
                        else max(0.0, settings.get("target_lost_grace_ms", 250) / 1000)
                    )
                    if not self.target_reference_is_valid(
                        previous_target_center,
                        last_target_seen_at,
                        selection_time,
                        reacquire_grace,
                    ):
                        previous_target_center = None
                        previous_aim_center = None
                        last_target_seen_at = None

                    target_match_missing = False
                    target_switched = False
                    if not detections.empty:
                        eligible_detections = detections.loc[
                            detections["confidence"] >= settings["confidence_threshold"]
                        ]
                        if previous_target_center is None:
                            eligible_detections = eligible_detections.nlargest(
                                settings["detection_limit"], "confidence"
                            )
                        if not eligible_detections.empty:
                            lock_radius = max(
                                48.0,
                                fov * 0.2,
                                float(settings.get("reacquire_radius_px", 0)),
                            )
                            if (
                                lock_active
                                and shoot_active
                                and settings.get("recoil_compensation", True)
                            ):
                                lock_radius = max(lock_radius, fov * 0.45)
                            candidate_index, lock_distance = self.select_target_index(
                                eligible_detections,
                                previous_target_center,
                                center_offset,
                                max_match_distance=lock_radius,
                            )
                            if candidate_index is None:
                                # Do not release a held target just because one
                                # frame has no box close to its last position.
                                # Keep the reference through the lock grace so a
                                # brief detector miss cannot switch aim to a rival.
                                if display is not None:
                                    for _, other in eligible_detections.iterrows():
                                        other_xmin, other_ymin, other_xmax, other_ymax = (
                                            other.iloc[:4].astype(float)
                                        )
                                        cv2.rectangle(
                                            display,
                                            (int(other_xmin), int(other_ymin)),
                                            (int(other_xmax), int(other_ymax)),
                                            (160, 160, 160),
                                            1,
                                        )
                                target_match_missing = True
                                candidate = eligible_detections.loc[
                                    eligible_detections["confidence"].idxmax()
                                ]
                                eligible_detections = eligible_detections.iloc[0:0]
                            else:
                                if previous_target_center is not None:
                                    priority_index = self.select_priority_target(
                                        eligible_detections,
                                        candidate_index,
                                        center_offset,
                                        fov,
                                        settings.get("target_priority_mode", "closest"),
                                        int(settings.get("target_stickiness", 2)),
                                        bool(settings.get("focus_single_target", True)),
                                        previous_target_center,
                                    )
                                    target_switched = priority_index != candidate_index
                                    candidate_index = priority_index
                                target_locked = (
                                    previous_target_center is not None and not target_switched
                                )
                                if target_switched:
                                    previous_aim_center = None
                                    filtered_target_center = None
                                    filtered_target_velocity = (0.0, 0.0)
                                    previous_filter_time = None
                                    target_lock_started_at = None
                                    last_click_at = None
                                    movement_remainder_x = 0.0
                                    movement_remainder_y = 0.0
                                    lock_smoothness_remainder_x = 0.0
                                    lock_smoothness_remainder_y = 0.0
                                    # New target: restart the crosshair reference.
                                    last_sent_aim_x = 0.0
                                    last_sent_aim_y = 0.0
                                candidate = eligible_detections.loc[candidate_index]
                                if display is not None:
                                    for other_index, other in eligible_detections.iterrows():
                                        if other_index == candidate_index:
                                            continue
                                        other_xmin, other_ymin, other_xmax, other_ymax = (
                                            other.iloc[:4].astype(float)
                                        )
                                        cv2.rectangle(
                                            display,
                                            (int(other_xmin), int(other_ymin)),
                                            (int(other_xmax), int(other_ymax)),
                                            (160, 160, 160),
                                            1,
                                        )
                        else:
                            candidate = detections.loc[detections["confidence"].idxmax()]
                        xmin, ymin, xmax, ymax = candidate.iloc[:4].astype(float)
                        confidence = float(candidate["confidence"])
                        target_center = ((xmin + xmax) / 2, (ymin + ymax) / 2)
                        cx, cy = self.get_aim_point(
                            xmin, ymin, xmax, ymax, settings["aim_height"]
                        )
                        accepted = not eligible_detections.empty
                        saw_target = accepted
                        action_allowed = (
                            accepted
                            and confidence >= settings["action_confidence_threshold"]
                        )
                        # Recoil compensation: while the shoot input is held the
                        # weapon kicks the view up, so bias the aim point down by a
                        # fraction of the box height to hold the head during a
                        # spray instead of riding the kick off target.
                        if (
                            action_allowed
                            and settings.get("recoil_compensation", True)
                            and shoot_active
                        ):
                            box_height = max(0.0, ymax - ymin)
                            strength = max(
                                0.0,
                                min(1.0, float(settings.get("recoil_strength", 65)) / 100.0),
                            )
                            cy += box_height * 0.18 * strength
                        if action_allowed:
                            filter_time = time.perf_counter()
                            if (
                                not target_locked
                                or filtered_target_center is None
                                or previous_filter_time is None
                                or previous_aim_center is None
                            ):
                                filtered_target_center = (cx, cy)
                                filtered_target_velocity = (0.0, 0.0)
                            else:
                                delta_time = max(filter_time - previous_filter_time, 0.001)
                                raw_velocity_x = (
                                    cx - previous_aim_center[0]
                                ) / delta_time
                                raw_velocity_y = (
                                    cy - previous_aim_center[1]
                                ) / delta_time
                                derivative_alpha = (
                                    2 * np.pi * delta_time
                                ) / (1 + 2 * np.pi * delta_time)
                                velocity_x = filtered_target_velocity[0] + derivative_alpha * (
                                    raw_velocity_x - filtered_target_velocity[0]
                                )
                                velocity_y = filtered_target_velocity[1] + derivative_alpha * (
                                    raw_velocity_y - filtered_target_velocity[1]
                                )
                                # Kalman tuning. Process/measurement noise set how
                                # eagerly the estimate follows the raw box versus
                                # trusting its own motion model; the speed
                                # multipliers scale the learned velocity per axis,
                                # and the reset threshold drops the estimate when a
                                # new box lands implausibly far from it (a target
                                # switch) instead of smearing across the gap.
                                process_noise = float(
                                    settings.get("kalman_process_noise", 40.0)
                                )
                                measurement_noise = float(
                                    settings.get("kalman_measurement_noise", 35.0)
                                )
                                speed_mult_x = float(
                                    settings.get("kalman_speed_multiplier_x", 1.0)
                                )
                                speed_mult_y = float(
                                    settings.get("kalman_speed_multiplier_y", 1.0)
                                )
                                reset_threshold = float(
                                    settings.get("kalman_reset_threshold", 400.0)
                                )
                                velocity_x *= speed_mult_x
                                velocity_y *= speed_mult_y
                                filtered_target_velocity = (velocity_x, velocity_y)
                                # Noise scales the cut-off: more process noise means
                                # follow the box faster, more measurement noise means
                                # smooth harder. The smoothness slider still biases
                                # the result, so it keeps working as a master control.
                                speed = float(np.hypot(velocity_x, velocity_y))
                                noise_ratio = process_noise / max(measurement_noise, 1.0)
                                cutoff = (
                                    12 / settings["smoothness"] * np.sqrt(noise_ratio)
                                    + 0.03 * speed * speed_mult_x
                                )
                                filter_alpha = min(
                                    1.0,
                                    (2 * np.pi * cutoff * delta_time)
                                    / (1 + 2 * np.pi * cutoff * delta_time),
                                )
                                filtered_target_center = (
                                    filtered_target_center[0]
                                    + filter_alpha * (cx - filtered_target_center[0]),
                                    filtered_target_center[1]
                                    + filter_alpha * (cy - filtered_target_center[1]),
                                )
                                if reset_threshold > 0.0:
                                    reset_dx = cx - filtered_target_center[0]
                                    reset_dy = cy - filtered_target_center[1]
                                    if float(np.hypot(reset_dx, reset_dy)) > reset_threshold:
                                        filtered_target_center = (cx, cy)
                                        filtered_target_velocity = (0.0, 0.0)
                            previous_filter_time = filter_time
                            dx = filtered_target_center[0] - center_offset
                            dy = filtered_target_center[1] - center_offset
                            # The detection is relative to the FOV centre, but the
                            # crosshair has already been moved by everything sent
                            # this lock (last_sent_aim_*). The remaining error is the
                            # target's offset MINUS that applied offset; measuring
                            # from the centre alone re-added the whole distance every
                            # frame so the aim overshot and ran off the target.
                            measured_dx = (cx - center_offset) - last_sent_aim_x
                            measured_dy = (cy - center_offset) - last_sent_aim_y
                            movement_dx = measured_dx
                            movement_dy = measured_dy
                            predicted_aim_center = (cx, cy)
                            if settings["prediction_enabled"]:
                                # Detection-delay compensation, adapted from the
                                # reference aimbot's prediction look-ahead: the
                                # configured horizon is a base lead, and the
                                # measured capture-to-detection latency is added
                                # on top so a moving target is led by the pipeline
                                # delay as well as the chosen horizon. Without
                                # this the aim always trails by one pipeline
                                # period on a fast target. Clamped so a single
                                # slow frame cannot fling the crosshair.
                                compensated_horizon_ms = settings["prediction_horizon_ms"]
                                if last_detection_ms and last_detection_ms > 0.0:
                                    compensated_horizon_ms = min(
                                        1500.0,
                                        compensated_horizon_ms + float(last_detection_ms),
                                    )
                                predicted_aim_center = self.predict_aim_point(
                                    (cx, cy),
                                    filtered_target_velocity,
                                    compensated_horizon_ms,
                                )
                                movement_dx = (
                                    predicted_aim_center[0] - center_offset
                                ) - last_sent_aim_x
                                movement_dy = (
                                    predicted_aim_center[1] - center_offset
                                ) - last_sent_aim_y
                            on_target = self.is_on_target(
                                (cx, cy), center_offset
                            )
                            if lock_active and on_target:
                                if target_lock_started_at is None:
                                    target_lock_started_at = filter_time
                                lock_elapsed_ms = (filter_time - target_lock_started_at) * 1000
                            else:
                                target_lock_started_at = None
                                lock_elapsed_ms = 0.0
                        else:
                            target_lock_started_at = None
                            previous_aim_center = None
                            filtered_target_center = None
                            filtered_target_velocity = (0.0, 0.0)
                            previous_filter_time = None
                            dx = cx - center_offset
                            dy = cy - center_offset
                            measured_dx = dx
                            measured_dy = dy
                            on_target = False
                            lock_elapsed_ms = 0.0
                        box_color = (
                            (160, 160, 160)
                            if target_match_missing
                            else
                            (0, 255, 255)
                            if action_allowed
                            else (0, 165, 255)
                            if accepted
                            else (0, 128, 255)
                        )
                        if display is not None:
                            cv2.rectangle(
                                display,
                                (int(xmin), int(ymin)),
                                (int(xmax), int(ymax)),
                                box_color,
                                2,
                            )
                            cv2.circle(display, (int(cx), int(cy)), 4, (0, 0, 255), -1)
                            if action_allowed:
                                cv2.circle(
                                    display,
                                    (
                                        int(filtered_target_center[0]),
                                        int(filtered_target_center[1]),
                                    ),
                                    6,
                                    (0, 255, 0),
                                    1,
                                    cv2.LINE_AA,
                                )
                                if settings["prediction_enabled"]:
                                    cv2.line(
                                        display,
                                        (int(cx), int(cy)),
                                        (
                                            int(predicted_aim_center[0]),
                                            int(predicted_aim_center[1]),
                                        ),
                                        (255, 255, 0),
                                        1,
                                        cv2.LINE_AA,
                                    )
                                    cv2.drawMarker(
                                        display,
                                        (
                                            int(predicted_aim_center[0]),
                                            int(predicted_aim_center[1]),
                                        ),
                                        (255, 255, 0),
                                        cv2.MARKER_CROSS,
                                        10,
                                        2,
                                        cv2.LINE_AA,
                                    )
                            cv2.putText(
                                display,
                                f"{'Holding target ' if target_match_missing else 'Selected ' if action_allowed else 'Low confidence ' if accepted else 'Below threshold '}"
                                f"{confidence:.0%} "
                                f"({int(cx)}, {int(cy)})",
                                (int(xmin), max(0, int(ymin) - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                (255, 255, 255),
                                2,
                            )
                        if accepted:
                            previous_target_center = target_center
                            previous_aim_center = (cx, cy)
                            last_target_seen_at = time.perf_counter()
                            if not action_allowed:
                                countdown_status = "Below action threshold"
                            elif not lock_active:
                                countdown_status = "Hold lock key"
                            elif not on_target:
                                countdown_status = "Move onto target"
                            elif lock_elapsed_ms >= settings["shot_delay_ms"]:
                                countdown_status = "Ready"
                            else:
                                countdown_status = (
                                    f"Settling {lock_elapsed_ms:.0f}/"
                                    f"{settings['shot_delay_ms']} ms"
                                )
                            self.on_detection(
                                f"Target center: ({cx:.1f}, {cy:.1f}) "
                                f"aim error: ({measured_dx:.1f}, {measured_dy:.1f}) "
                                f"confidence: {confidence:.1%} "
                                f"aim status: {countdown_status}"
                            )

                        if action_allowed:
                            if lock_active:
                                if sigma_drift is not None:
                                    # SigmaDrift generates the whole trajectory.
                                    # Plan a stroke when none is in flight, then
                                    # advance it by the real frame interval. It
                                    # replaces the legacy correction entirely, so
                                    # the two are never summed (that would double
                                    # the intended distance).
                                    now_frame = time.perf_counter()
                                    elapsed_ms = (now_frame - last_frame_time) * 1000.0
                                    last_frame_time = now_frame
                                    if not sigma_drift.active and settings.get(
                                        "movement_method", "sigmadrift"
                                    ).lower() == "sigmadrift":
                                        sigma_drift.begin_move(
                                            last_sent_aim_x,
                                            last_sent_aim_y,
                                            last_sent_aim_x + movement_dx,
                                            last_sent_aim_y + movement_dy,
                                        )
                                    if sigma_drift.active:
                                        (
                                            move_x,
                                            move_y,
                                            movement_remainder_x,
                                            movement_remainder_y,
                                            sigma_drift_active,
                                        ) = sigma_drift.step(
                                            elapsed_ms,
                                            movement_remainder_x,
                                            movement_remainder_y,
                                        )
                                    else:
                                        move_x = 0
                                        move_y = 0
                                elif settings.get("hard_lock", False):
                                    # Start with the full direct correction; the
                                    # lock-smoothness control below shapes the sent step.
                                    last_frame_time = time.perf_counter()
                                    move_x = int(round(movement_dx))
                                    move_y = int(round(movement_dy))
                                    movement_remainder_x = 0.0
                                    movement_remainder_y = 0.0
                                else:
                                    last_frame_time = time.perf_counter()
                                    move_x, movement_remainder_x = self.movement_step(
                                        movement_dx,
                                        settings["smoothness"],
                                        movement_remainder_x,
                                        settings["aiming_curve"],
                                    )
                                    move_y, movement_remainder_y = self.movement_step(
                                        movement_dy,
                                        settings["smoothness"],
                                        movement_remainder_y,
                                        settings["aiming_curve"],
                                    )
                                divisor = max(
                                    1.0,
                                    min(
                                        10.0,
                                        float(settings.get("lock_smoothness", 1.0)),
                                    ),
                                )
                                scaled_x = move_x / divisor + lock_smoothness_remainder_x
                                scaled_y = move_y / divisor + lock_smoothness_remainder_y
                                move_x = int(
                                    math.copysign(math.floor(abs(scaled_x) + 0.5), scaled_x)
                                )
                                move_y = int(
                                    math.copysign(math.floor(abs(scaled_y) + 0.5), scaled_y)
                                )
                                lock_smoothness_remainder_x = scaled_x - move_x
                                lock_smoothness_remainder_y = scaled_y - move_y
                                last_sent_aim_x += move_x
                                last_sent_aim_y += move_y
                            else:
                                move_x = 0
                                move_y = 0
                                movement_remainder_x = 0.0
                                movement_remainder_y = 0.0
                                lock_smoothness_remainder_x = 0.0
                                lock_smoothness_remainder_y = 0.0
                                # Lock not held: the crosshair reference no longer
                                # tracks a lock, so clear it and let the next hold
                                # measure from a fresh start.
                                last_sent_aim_x = 0.0
                                last_sent_aim_y = 0.0
                                if sigma_drift is not None:
                                    sigma_drift.stop()
                                last_frame_time = time.perf_counter()
                            now = time.perf_counter()
                            click_due = self.click_is_due(
                                lock_active,
                                on_target,
                                lock_elapsed_ms,
                                settings["shot_delay_ms"],
                                shoot_active,
                                last_click_at,
                                now,
                                settings["shot_interval_ms"],
                            )
                            if lock_active or click_due:
                                sent = self.send_adjustment(
                                    move_x, move_y, click=click_due
                                )
                                if sent and click_due:
                                    last_click_at = now
                        elif not accepted:
                            target_lock_started_at = None
                            previous_aim_center = None
                            filtered_target_center = None
                            filtered_target_velocity = (0.0, 0.0)
                            previous_filter_time = None
                            last_click_at = None
                            if sigma_drift is not None:
                                sigma_drift.stop()
                            if target_match_missing:
                                self.on_detection(
                                    "Holding current target selection; waiting for it to reappear"
                                )
                            else:
                                self.on_detection(
                                    f"Candidate ignored: confidence {confidence:.1%} is below the "
                                    f"{settings['confidence_threshold']:.0%} minimum"
                                )
                            movement_remainder_x = 0.0
                            movement_remainder_y = 0.0
                            lock_smoothness_remainder_x = 0.0
                            lock_smoothness_remainder_y = 0.0
                        elif not action_allowed:
                            previous_aim_center = None
                            filtered_target_center = None
                            filtered_target_velocity = (0.0, 0.0)
                            previous_filter_time = None
                            last_click_at = None
                            if sigma_drift is not None:
                                sigma_drift.stop()
                            self.on_detection(
                                f"Target selected ({confidence:.1%}), below the "
                                f"{settings['action_confidence_threshold']:.0%} action confidence threshold"
                            )
                            movement_remainder_x = 0.0
                            movement_remainder_y = 0.0
                            lock_smoothness_remainder_x = 0.0
                            lock_smoothness_remainder_y = 0.0
                        else:
                            movement_remainder_x = 0.0
                            movement_remainder_y = 0.0
                    else:
                        if not self.target_reference_is_valid(
                            previous_target_center,
                            last_target_seen_at,
                            time.perf_counter(),
                            reacquire_grace,
                        ):
                            previous_target_center = None
                            last_target_seen_at = None
                        target_lock_started_at = None
                        previous_aim_center = None
                        filtered_target_center = None
                        filtered_target_velocity = (0.0, 0.0)
                        previous_filter_time = None
                        last_click_at = None
                        if sigma_drift is not None:
                            sigma_drift.stop()
                        if inference_paused:
                            self.on_detection("Waiting for Lock input; inference paused")
                        elif captured_detection_count == 0:
                            self.on_detection("No detections in captured area")
                        elif settings["fov_shape"] == "Circle":
                            self.on_detection("Detections outside circular FOV")
                        else:
                            self.on_detection("No detections inside FOV")
                        movement_remainder_x = 0.0
                        movement_remainder_y = 0.0
                        # Target lost: the lock is over, so the crosshair
                        # reference is stale; start clean on re-acquisition.
                        last_sent_aim_x = 0.0
                        last_sent_aim_y = 0.0

                    processing_completed_at = time.perf_counter()
                    # The processing slice, used for the per-stage timings.
                    elapsed = processing_completed_at - frame_started
                    preview_started_at = time.perf_counter()
                    # Boxes travel with the preview so the GUI can draw them. They
                    # are in FOV-crop pixels -- the same space as ``display`` and
                    # the native engine's PREVIEW line -- so the consumer scales
                    # them to whatever preview size it renders.
                    if display is not None:
                        preview_boxes = [
                            (
                                float(row[0]), float(row[1]),
                                float(row[2]), float(row[3]),
                                float(row[4]), 0,
                            )
                            for row in detections.itertuples(index=False)
                        ]
                        self.on_preview(display, preview_boxes)
                        preview_last_at = preview_completed_at = time.perf_counter()
                    else:
                        preview_completed_at = processing_completed_at
                    frame_sequence += 1
                    frame_timings = {
                        "capture": (capture_completed_at - capture_started_at) * 1000,
                        "prepare": (prepare_completed_at - prepare_started_at) * 1000,
                        "predict": (predict_completed_at - predict_started_at) * 1000,
                        "transfer_decode": (
                            transfer_decode_completed_at - transfer_decode_started_at
                        ) * 1000,
                        "postprocess": (
                            processing_completed_at - transfer_decode_completed_at
                        ) * 1000,
                        "preview": (preview_completed_at - preview_started_at) * 1000,
                        "detection": (
                            processing_completed_at - capture_started_at
                        ) * 1000,
                        "pipeline": (preview_completed_at - capture_started_at) * 1000,
                    }
                    self.on_latency(frame_timings["detection"])
                    last_detection_ms = frame_timings["detection"]
                    for name, duration in frame_timings.items():
                        timing_samples[name].append(duration)
                    sample_now = time.perf_counter()
                    telemetry_due = (
                        frame_sequence == 1
                        or sample_now - telemetry_last_write >= telemetry_min_interval
                    )
                    telemetry_full = (
                        telemetry_rows_written >= TELEMETRY_MAX_ROWS
                        or telemetry_file is not None
                        and telemetry_file.tell() >= TELEMETRY_MAX_BYTES
                    )
                    if telemetry_writer is not None and telemetry_due and not telemetry_full:
                        try:
                            telemetry_last_write = sample_now
                            telemetry_rows_written += 1
                            telemetry_writer.writerow(
                                {
                                    "timestamp_utc": capture_timestamp_utc,
                                    "sequence": frame_sequence,
                                    "model": Path(active_model_path).name,
                                    "device": str(self.device),
                                    "capture_ms": frame_timings["capture"],
                                    "prepare_ms": frame_timings["prepare"],
                                    "predict_call_ms": frame_timings["predict"],
                                    "result_transfer_decode_ms": frame_timings[
                                        "transfer_decode"
                                    ],
                                    "postprocess_ms": frame_timings["postprocess"],
                                    "preview_submit_ms": frame_timings["preview"],
                                    "capture_to_detection_ms": frame_timings[
                                        "detection"
                                    ],
                                    "capture_to_preview_submit_ms": frame_timings[
                                        "pipeline"
                                    ],
                                }
                            )
                            # Periodic flush is cheap at the sampled rate and keeps
                            # a crash from losing the tail of the file.
                            telemetry_file.flush()
                            if telemetry_full and not telemetry_capped_notified:
                                telemetry_capped_notified = True
                                self.on_status(
                                    "Pipeline telemetry reached its size cap; "
                                    "logging stopped for this session."
                                )
                        except OSError as exc:
                            self.on_status(
                                f"Pipeline telemetry write failed; logging disabled: {exc}"
                            )
                            try:
                                telemetry_file.close()
                            except OSError as close_exc:
                                self.on_status(
                                    f"Could not close pipeline telemetry file: {close_exc}"
                                )
                            telemetry_file = None
                            telemetry_writer = None
                    if frame_sequence % 15 == 0:
                        summary = {}
                        for name, values in timing_samples.items():
                            ordered = sorted(values)
                            count = len(ordered)
                            median = (
                                ordered[count // 2]
                                if count % 2
                                else (ordered[count // 2 - 1] + ordered[count // 2]) / 2
                            )
                            p95 = ordered[min(count - 1, math.ceil(0.95 * count) - 1)]
                            summary[name] = {"median": median, "p95": p95}
                        self.on_pipeline_metrics(
                            {"sequence": frame_sequence, "stages": summary}
                        )
                except Exception as exc:
                    previous_target_center = None
                    previous_aim_center = None
                    target_lock_started_at = None
                    filtered_target_center = None
                    filtered_target_velocity = (0.0, 0.0)
                    previous_filter_time = None
                    lock_smoothness_remainder_x = 0.0
                    lock_smoothness_remainder_y = 0.0
                    self.on_status(f"Loop error: {exc}")
                    self.on_fps(0.0)
                    time.sleep(0.5)
                    continue

                # Graduated idle back-off. `saw_target` is set by the target
                # stage below; when it is False for a run of frames the loop
                # sleeps just long enough to hold the idle frame rate, capped so
                # responsiveness returns quickly once something appears.
                if saw_target:
                    idle_frames = 0
                else:
                    idle_frames += 1
                if idle_backoff_enabled and idle_frames > IDLE_GRACE_FRAMES and idle_fps_floor > 0.0:
                    frame_elapsed = time.perf_counter() - frame_started
                    target_interval = 1.0 / idle_fps_floor
                    if frame_elapsed < target_interval:
                        # Sleep the remainder, but never longer than the idle
                        # interval, so the engine stays responsive.
                        time.sleep(min(target_interval - frame_elapsed, target_interval))
                # Optional detection-rate cap. Zero means unlimited: the loop runs
                # as fast as capture and inference allow, which is the fastest
                # path. A non-zero value sleeps off the rest of the frame budget
                # so the GPU is not saturated, at the cost of detection rate.
                if detection_fps_limit > 0.0:
                    frame_elapsed = time.perf_counter() - frame_started
                    budget = 1.0 / detection_fps_limit
                    if frame_elapsed < budget:
                        time.sleep(budget - frame_elapsed)
                # Report the real detection rate, not the idle-throttled loop rate.
                # With idle back-off on, the loop deliberately sleeps on an empty
                # screen, so a raw 1/elapsed figure reads the 20 fps floor as if the
                # pipeline had slowed when a full detection still costs a millisecond
                # or two. Using the measured detection time shows the capability that
                # is actually there, which is what the dashboard is reporting.
                if last_detection_ms and last_detection_ms > 0.0:
                    self.on_fps(1000.0 / last_detection_ms)
                else:
                    loop_elapsed = time.perf_counter() - frame_started
                    self.on_fps(1.0 / loop_elapsed if loop_elapsed > 0 else 0.0)
        finally:
            if telemetry_file is not None:
                try:
                    telemetry_file.flush()
                    telemetry_file.close()
                except OSError as exc:
                    self.on_status(f"Could not finish pipeline telemetry file: {exc}")
            self.close()
            self.on_status("DisabledAssistance loop stopped")

    def close(self):
        self._release_capture_resources()
        if self.arduino is not None and self.arduino.is_open:
            self.arduino.close()
        self.arduino = None
        self._connected_port = None


def main():
    stop_event = threading.Event()
    engine = DisabledAssistanceEngine()
    try:
        engine.run(stop_event)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        engine.close()


if __name__ == "__main__":
    main()
