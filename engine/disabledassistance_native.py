"""Bridge that runs the native C++/CUDA/TensorRT engine instead of the Python one.

The GUI talks to a small callback contract (``on_status``, ``on_detection``,
``on_fps``, ``on_pipeline_metrics``, ``on_preview``). The native engine exposes a
command-line program instead of a Python object, so this module:

1. writes the current GUI settings to a JSON file the native binary understands,
2. launches ``native_engine.exe`` bound to that file,
3. parses the engine's stdout and translates it into the same callbacks, and
4. stops the process cleanly when the GUI asks it to.

This keeps the control panel unchanged while the capture, CUDA preprocessing,
TensorRT inference, target tracking, and serial output all run in native code.
"""

import base64
import binascii
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

# This module lives in engine/, so the project root -- the folder that holds
# native/, models/ and config/ -- is its parent. Using the module's own folder
# here made the native executable lookups below search engine/native/..., which
# never exists, so find_native_engine() always returned None and the GUI silently
# fell back to the slower Python engine. That is what cost two thirds of the
# frame rate and fed the fixed-shape TensorRT engine the wrong tensor size.
ROOT_DIR = Path(__file__).resolve().parent.parent

# The native build produced by native/CMakeLists.txt. Both the Ninja and the
# Visual Studio generator layouts are probed so either build works.
NATIVE_EXE_CANDIDATES = (
    ROOT_DIR / "native" / "build-ninja" / "native_engine.exe",
    ROOT_DIR / "native" / "build-ninja" / "Release" / "native_engine.exe",
    ROOT_DIR / "native" / "build" / "Release" / "native_engine.exe",
    ROOT_DIR / "native" / "build" / "native_engine.exe",
    ROOT_DIR / "native" / "build-ninja" / "native_engine",
)


def find_native_engine():
    """Return the native engine executable path, or None when it is not built."""
    override = os.environ.get("DISABLED_ASSISTANCE_NATIVE_ENGINE")
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    for candidate in NATIVE_EXE_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _parse_preview_boxes(payload):
    """Parse the trailing box list from a PREVIEW line.

    The engine appends ``x1,y1,x2,y2,conf,class;`` entries in FOV-crop pixel
    coordinates. A malformed or missing payload simply yields no boxes rather
    than failing the frame, so an older engine or a truncated line still shows
    the image.
    """
    boxes = []
    if not payload:
        return boxes
    for entry in payload.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(",")
        if len(parts) != 6:
            continue
        try:
            x1, y1, x2, y2, confidence, class_id = (
                float(parts[0]), float(parts[1]), float(parts[2]),
                float(parts[3]), float(parts[4]), int(float(parts[5])),
            )
        except ValueError:
            continue
        boxes.append((x1, y1, x2, y2, confidence, class_id))
    return boxes


def _clamp(value, fallback, minimum=None, maximum=None):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = fallback
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _input_binding(value):
    """Serialise a lock/shoot binding for the native config.

    The GUI's keybind control stores a Windows virtual-key code as an int, but a
    JSON round-trip can hand back a float (2.0). Writing that straight with
    ``str()`` produced ``"2.0"``, which the native ``std::stol`` rejects, so the
    binding silently resolved to no key and the assistant never locked on. A
    raw number is therefore always written as a plain integer string; anything
    else (a key name such as ``"Left mouse"`` or ``"Auto"``) is passed through.
    """
    if isinstance(value, bool):
        return "0"
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value)


class NativeEngineBackend:
    """Runs ``native_engine.exe`` and maps its output onto the GUI callbacks.

    It mirrors the subset of ``DisabledAssistanceEngine`` that the GUI uses:
    ``update_settings``, ``run(stop_event)``, ``close``, ``send_adjustment``,
    ``device`` and ``model``. Inference itself happens in the native process.
    """

    USER_STATUS_PREFIX = "NATIVE "

    def __init__(
        self,
        on_status=None,
        on_detection=None,
        on_fps=None,
        on_pipeline_metrics=None,
        on_preview=None,
        on_latency=None,
        executable=None,
        config_path=None,
    ):
        self.on_status = on_status or (lambda _message: None)
        self.on_detection = on_detection or (lambda _message: None)
        self.on_fps = on_fps or (lambda _fps: None)
        self.on_pipeline_metrics = on_pipeline_metrics or (lambda _metrics: None)
        self.on_preview = on_preview or (lambda _image: None)
        self.on_latency = on_latency or (lambda _latency_ms: None)

        self.executable = Path(executable) if executable else find_native_engine()
        # Generated config the native binary reads; kept beside the GUI's own
        # settings under config/ so the project root stays uncluttered.
        self.config_path = Path(config_path) if config_path else (
            ROOT_DIR / "config" / "native_engine_config.json"
        )

        self._settings_lock = threading.Lock()
        self._settings = {}
        self.model = None
        self.device = "cuda"
        self._process = None
        self._reader = None
        self._stderr_reader = None
        self._stop_requested = threading.Event()
        self._last_capture_to_detection_ms = None

    # -- settings ---------------------------------------------------------
    def update_settings(self, settings):
        with self._settings_lock:
            self._settings.update(settings)
            # Persist straight away, not only when run() launches the process.
            # The native engine reads its settings once at startup, so a config
            # written only at launch means any setting changed afterwards (such
            # as the live preview stream) is silently lost the next time the
            # engine starts. Refreshing the file here keeps the on-disk config
            # in step with the UI, and lets a running engine pick up the live
            # preview keys it re-reads every frame.
            self._write_config_locked()

    def _settings_snapshot(self):
        with self._settings_lock:
            return dict(self._settings)

    # -- config -----------------------------------------------------------
    def _native_config(self, settings):
        """Translate GUI settings into the keys the native engine reads.

        Confidence values arrive as 0-1 from the GUI but the config file stores
        0-100; the native loader accepts either, so percentages are written to
        stay consistent with ``disabledassistance_config.json``.
        """
        # The GUI stores the screen resolution as ScreenResX / ScreenResY. The
        # native engine reads width / height, so translate here (accepting the
        # old names too) rather than making the C++ side understand GUI naming.
        width = _clamp(settings.get("ScreenResX", settings.get("width")), 1920, 1)
        height = _clamp(settings.get("ScreenResY", settings.get("height")), 1080, 1)
        fov = _clamp(settings.get("fov"), 320, 1)
        config = {
            "model_path": str(settings.get("model_path", "")),
            "port": str(settings.get("port", "")),
            "lock_key": _input_binding(settings.get("lock_key", "Alt")),
            "shoot_input": _input_binding(settings.get("shoot_input", "Left mouse")),
            "aiming_curve": str(settings.get("aiming_curve", "Linear")),
            "fov_shape": str(settings.get("fov_shape", "Square")),
            "fov": fov,
            "width": width,
            "height": height,
            "offset_x": _clamp(settings.get("offset_x"), 0),
            "offset_y": _clamp(settings.get("offset_y"), 0),
            "detection_limit": _clamp(settings.get("detection_limit"), 5, 1),
            "shot_delay_ms": _clamp(settings.get("shot_delay_ms"), 150, 0),
            "shot_interval_ms": _clamp(settings.get("shot_interval_ms"), 250, 0),
            "prediction_horizon_ms": _clamp(settings.get("prediction_horizon_ms"), 100, 0),
            "aim_height": float(settings.get("aim_height", 100.0)),
            "smoothness": max(float(settings.get("smoothness", 1.0)), 1e-3),
            "confidence_threshold": round(float(settings.get("confidence_threshold", 0.25)) * 100, 2),
            "action_confidence_threshold": round(
                float(settings.get("action_confidence_threshold", 0.50)) * 100, 2
            ),
            # NMS overlap threshold, passed straight through (already 0-1).
            "iou_threshold": float(settings.get("iou_threshold", 0.45)),
            "prediction_enabled": bool(settings.get("prediction_enabled", False)),
            # Movement generation: "sigmadrift" (biomechanical model) or "legacy".
            "movement_method": str(settings.get("movement_method", "sigmadrift")),
            # SigmaDrift tuning. Snap is the day-to-day control (0 slow, 100
            # instant); the rest are the biomechanical shape knobs. Passed through
            # so tuning them in the GUI actually reaches the native engine.
            "sigmadrift_snap": float(settings.get("sigmadrift_snap", 80)),
            "sigmadrift_target_width": float(settings.get("sigmadrift_target_width", 20.0)),
            "sigmadrift_curvature_scale": float(
                settings.get("sigmadrift_curvature_scale", 0.025)
            ),
            "sigmadrift_overshoot_prob": float(
                settings.get("sigmadrift_overshoot_prob", 0.15)
            ),
            "sigmadrift_ou_sigma": float(settings.get("sigmadrift_ou_sigma", 1.2)),
            "sigmadrift_tremor_amp_max": float(
                settings.get("sigmadrift_tremor_amp_max", 0.55)
            ),
            "sigmadrift_sdn_k": float(settings.get("sigmadrift_sdn_k", 0.04)),
            "sigmadrift_sample_dt_mean": float(
                settings.get("sigmadrift_sample_dt_mean", 7.8)
            ),
            # Recoil compensation keeps the aim on the head during sustained fire.
            "recoil_compensation": bool(settings.get("recoil_compensation", True)),
            "recoil_strength": float(settings.get("recoil_strength", 65)),
            # Hard lock: rigid, minimum-latency tracking that puts the crosshair on
            # the target each frame instead of following a trajectory behind it.
            "hard_lock": bool(settings.get("hard_lock", False)),
            "capture_backend": str(settings.get("capture_backend", "dxgi")),
            "input_backend": str(settings.get("input_backend", "arduino")),
            "movement_smoothing_enabled": bool(
                settings.get("movement_smoothing_enabled", True)
            ),
            "movement_max_step_px": float(settings.get("movement_max_step_px", 60)),
            "movement_acceleration": max(
                float(settings.get("movement_acceleration", 35)) / 100.0, 0.01
            ),
            "movement_stop_tolerance_px": max(
                float(settings.get("movement_stop_tolerance_px", 2)) / 10.0, 0.0
            ),
            "dataset_enabled": bool(settings.get("dataset_enabled", False)),
            "dataset_save_frames": bool(settings.get("dataset_save_frames", True)),
            "dataset_min_confidence": round(
                float(settings.get("dataset_min_confidence", 55)) / 100.0, 3
            ),
            "dataset_max_frames_per_second": _clamp(
                settings.get("dataset_max_frames_per_second"), 5, 1
            ),
            "dataset_dir": str(settings.get("dataset_dir", "dataset")),
            # Targeting: how a target is ranked, how stubbornly it is held, and
            # how long a lost target is remembered before re-acquisition.
            "target_priority_mode": str(settings.get("target_priority_mode", "closest")),
            "target_stickiness": _clamp(settings.get("target_stickiness"), 2, 0),
            "focus_single_target": bool(settings.get("focus_single_target", True)),
            "target_lost_grace_ms": _clamp(settings.get("target_lost_grace_ms"), 250, 0),
            "reacquire_radius_px": _clamp(settings.get("reacquire_radius_px"), 120, 0),
            # Kalman target-prediction filter. The native loader clamps and
            # defaults each key, so a partial config still runs.
            "kalman_enabled": bool(settings.get("kalman_enabled", True)),
            "kalman_process_noise": float(settings.get("kalman_process_noise", 40.0)),
            "kalman_measurement_noise": float(
                settings.get("kalman_measurement_noise", 35.0)
            ),
            "kalman_speed_multiplier_x": float(
                settings.get("kalman_speed_multiplier_x", 1.0)
            ),
            "kalman_speed_multiplier_y": float(
                settings.get("kalman_speed_multiplier_y", 1.0)
            ),
            "kalman_reset_threshold": float(
                settings.get("kalman_reset_threshold", 400.0)
            ),
            # Diagnostics. The native engine treats a missing telemetry key as
            # "off", so an old build simply never writes a CSV.
            "telemetry_csv_enabled": bool(settings.get("telemetry_csv_enabled", False)),
            "idle_backoff_enabled": bool(settings.get("idle_backoff_enabled", False)),
            "idle_fps_floor": _clamp(settings.get("idle_fps_floor"), 20, 1),
            # Optional detection-rate cap. 0 = unlimited (the fast default).
            # The maximum must be a real ceiling, not 0: clamping to (0, 0)
            # forced every value back to unlimited, so the GUI slider and the
            # idle back-off it was meant to complement could never take effect.
            "detection_fps_limit": _clamp(settings.get("detection_fps_limit"), 0, 0, 1000),
            "inference_only_when_aiming": bool(
                settings.get("inference_only_when_aiming", False)
            ),
            # Live preview streaming to the GUI, decoupled from inference.
            "preview_stream_enabled": bool(settings.get("floating_preview", True)),
            "preview_fps": _clamp(settings.get("preview_fps"), 20, 1),
            "preview_size": _clamp(settings.get("preview_size"), 240, 64),
        }
        return config

    def _write_config(self):
        return self._write_config_locked()

    def _write_config_locked(self):
        """Serialise the current settings to the native engine's config file.

        Callers must already hold ``self._settings_lock`` when coming from
        ``update_settings``; ``_write_config`` takes the snapshot first. The
        write is atomic (write to a sibling temp file, then replace) so the
        engine never reads a half-written file when it polls for live updates.
        """
        settings = dict(self._settings)
        config = self._native_config(settings)
        self.model = config["model_path"]
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
        os.replace(temporary, self.config_path)
        return config

    # -- data port (native engine -> GUI) --------------------------------
    def push_frame(self, sequence, capture_ms, predict_ms, capture_to_detection_ms):
        """Feed one native telemetry sample into the GUI's metrics pipeline."""
        stages = {}
        for name in (
            "capture",
            "prepare",
            "predict",
            "transfer_decode",
            "postprocess",
            "preview",
            "detection",
            "pipeline",
        ):
            stages[name] = {"median": 0.0, "p95": 0.0}
        stages["capture"]["median"] = stages["capture"]["p95"] = capture_ms
        stages["predict"]["median"] = stages["predict"]["p95"] = predict_ms
        stages["detection"]["median"] = stages["detection"]["p95"] = capture_to_detection_ms
        stages["pipeline"]["median"] = stages["pipeline"]["p95"] = capture_to_detection_ms
        self._last_capture_to_detection_ms = capture_to_detection_ms
        self.on_pipeline_metrics({"sequence": sequence, "stages": stages})
        self.on_latency(capture_to_detection_ms)

    # -- process lifecycle -------------------------------------------------
    def run(self, stop_event):
        if self.executable is None:
            raise FileNotFoundError(
                "Native engine executable not found. Build native/ first "
                "(see README 'Native C++ / CUDA / TensorRT engine'), or set "
                "DISABLED_ASSISTANCE_NATIVE_ENGINE to its path."
            )
        if not self.executable.is_file():
            raise FileNotFoundError(f"Native engine executable not found: {self.executable}")

        config = self._write_config()
        model_path = Path(config["model_path"])
        if not model_path.is_file():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        self._stop_requested.clear()
        self.on_status(f"NATIVE Launching {self.executable.name}")

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [str(self.executable), str(self.config_path)],
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )

        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(
            target=self._read_stream, args=(self._process.stderr, "NATIVE stderr: "), daemon=True
        )
        self._reader.start()
        self._stderr_reader.start()

        try:
            while True:
                if stop_event.is_set() or self._stop_requested.is_set():
                    break
                if self._process.poll() is not None:
                    break
                time.sleep(0.1)
        finally:
            self._shutdown()

        return_code = self._process.returncode if self._process else None
        if return_code not in (None, 0) and not stop_event.is_set():
            raise RuntimeError(f"Native engine exited with code {return_code}")

    def _shutdown(self):
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._process = None

    def close(self):
        """Match the Python engine API so the GUI can stop cleanly."""
        self._stop_requested.set()
        self._shutdown()

    def send_adjustment(self, x, y, click=False):
        """The native engine owns the serial port while it runs.

        A manual test packet is therefore only possible after the engine has
        stopped, so this reports that the active session owns the connection.
        """
        if self._process is not None and self._process.poll() is None:
            return False
        return False

    # -- output parsing ----------------------------------------------------
    def _read_stream(self, stream, prefix):
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            text = line.strip()
            if text:
                self.on_status(f"{prefix}{text}")
        stream.close()

    def _read_stdout(self):
        stream = self._process.stdout if self._process else None
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            self._handle_line(line.strip())
        stream.close()

    def _handle_line(self, line):
        if not line:
            return
        if line.startswith("FRAME #"):
            self._handle_frame(line)
            return
        if line.startswith("PREVIEW "):
            self._handle_preview(line)
            return
        if line.startswith("TensorRT input "):
            self.on_status(f"NATIVE {line}")
            return
        if line.startswith("Loading native engine"):
            self.on_status("Loading model (native)")
            return
        if line.startswith("Pipeline telemetry"):
            self.on_status(f"NATIVE {line}")
            return
        if line.startswith("Native process priority"):
            return
        if line.startswith("DisabledAssistance native loop stopped"):
            return
        self.on_status(f"NATIVE {line}")

    _FRAME_PATTERN = re.compile(
        r"FRAME #(?P<sequence>\d+)\s+fps=(?P<fps>[-+0-9.eE]+)"
        r"(?:\s+detection_fps=(?P<dfps>[-+0-9.eE]+))?"
        r"\s+capture=(?P<capture>[-+0-9.eE]+)ms"
        r"\s+predict=(?P<predict>[-+0-9.eE]+)ms"
        r"\s*(?P<status>.*)"
    )
    # "PREVIEW <w> <h> <base64 BGR>[ x1,y1,x2,y2,conf,class;...]" streamed by the
    # native engine at a fixed cadence, decoupled from the detection rate. The
    # trailing box list is optional so an older engine build still parses.
    _PREVIEW_PATTERN = re.compile(
        r"PREVIEW (?P<w>\d+) (?P<h>\d+) (?P<data>[A-Za-z0-9+/=]+)(?: (?P<boxes>.*))?"
    )

    def _handle_preview(self, line):
        """Decode one streamed native preview into the GUI's preview queue."""
        match = self._PREVIEW_PATTERN.match(line)
        if match is None:
            return
        width = int(match.group("w"))
        height = int(match.group("h"))
        try:
            payload = base64.b64decode(match.group("data"), validate=True)
        except (binascii.Error, ValueError):
            return
        expected = width * height * 3
        if width <= 0 or height <= 0 or len(payload) != expected:
            return
        frame = np.frombuffer(payload, dtype=np.uint8).reshape((height, width, 3))
        # The engine streams BGR; OpenCV's preview path and the GUI both expect
        # BGR, so no channel swap is needed. enqueue raw so boxes can be drawn.
        self.on_preview(np.ascontiguousarray(frame), _parse_preview_boxes(match.group("boxes")))

    def _handle_frame(self, line):
        # Example: "FRAME #60 fps=336.54 capture=1.6655ms predict=0.95635ms <status>"
        match = self._FRAME_PATTERN.match(line)
        if match is None:
            return

        sequence = int(match.group("sequence"))
        try:
            fps = float(match.group("fps"))
            capture_ms = float(match.group("capture"))
            predict_ms = float(match.group("predict"))
        except ValueError:
            return
        # Prefer the reported detection rate when the engine provides it: it is
        # the real search speed, not the idle-throttled loop rate.
        raw_dfps = match.group("dfps")
        if raw_dfps is not None:
            try:
                detection_fps = float(raw_dfps)
            except ValueError:
                detection_fps = None
            if detection_fps is not None and detection_fps > 0:
                fps = detection_fps

        status = match.group("status").strip()
        capture_to_detection_ms = capture_ms + predict_ms

        self.on_fps(fps)
        if status:
            self.on_detection(status)
        self.push_frame(sequence, capture_ms, predict_ms, capture_to_detection_ms)
