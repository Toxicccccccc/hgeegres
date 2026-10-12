# 🎮 DisabledAssistance – A Competitive Game Built Around AI Assistance

DisabledAssistance is a **competitive game for players with disabilities**, where **AI assistance is part of the rules, not an exception to them**. Every player is paired with a real-time AI assistant that helps with targeting and input. Because everyone is assisted by design, matches are decided by strategy, adaptation and how well you tune and use your assistant, rather than by raw motor precision.

The assistance layer is a **real-time object-detection pipeline** (YOLOv8 / TensorRT, CUDA-accelerated on NVIDIA GPUs) that locates targets on screen and converts them into smoothed input corrections. The Python GUI remains the control panel; a native C++ engine in `native/` is the performance path for capture, TensorRT inference, target tracking, and Arduino output.

> ⚠️ **Project status: early development.** The assistance engine and control panel described below are working components. Game modes, matchmaking and level design are in progress and are listed under [Roadmap](#-roadmap).

---

## 🎯 Project Goals

- **Make competition accessible.** Give players who struggle with fine motor control, tremors, limited mobility or reaction-time barriers a way to compete on equal terms.
- **Make assistance the mechanic.** Each player's assist profile is visible, configurable and part of the match, so the contest is about decisions and tuning, not hidden advantages.
- **Keep it transparent.** Assistance levels are explicit settings. Nothing is concealed from opponents or from the game.
- **Keep it measurable.** Built-in telemetry shows exactly how much latency and processing the assistant adds.

---

## 🧩 Core Concept

| Element | Description |
|---|---|
| **Assisted by default** | Every participant uses an AI assistant. There is no "unassisted" side. |
| **Assist profiles** | Aim height, smoothness, aiming curve, prediction look-ahead, lock delay and click interval are all adjustable per player. |
| **Fairness through parity** | Matches can enforce shared limits on profile values (for example, a maximum smoothing speed or minimum lock delay). |
| **Skill expression** | Winning comes from positioning, timing, tuning your profile and reading your opponent's, not from motor speed. |

---

## 🏗️ How the Assistance Engine Works

1. **Capture** – A configurable region of the screen is captured (Windows GDI; context and bitmap are reused between frames and recreated only when capture size changes).
2. **Detect** – A YOLOv8 model (`.pt` or TensorRT `.engine`) runs at `imgsz=640` and returns up to 1–5 candidate detections.
3. **Select & filter** – Candidates are filtered by minimum and action confidence thresholds.
4. **Correct** – While the player holds the **Lock key**, movement correction is computed using the profile's smoothness, curve, prediction and delay settings.
5. **Act** – While the configured **Shoot input** is held, clicks are issued at the configured interval.
6. **Output** – Input is sent through an **Arduino Leonardo + USB Host Shield 2.0**, which presents itself to Windows as a standard HID mouse. The firmware receives separate movement and click flags.

The displayed confidence is the model's score, not a calibrated probability that a detection is correct.

---

## 🖥️ System Requirements

- **GPU:** NVIDIA RTX 2060 (minimum), RTX 3050 (recommended), RTX 4060 or better for the lowest latency (reduce `time.sleep` to `0.01` in the `.py` file)
- **OS:** Windows
- **Python:** 3.9.10 (recommended) or later
- **Hardware:** Arduino Leonardo, USB Host Shield 2.0

---

## ⚙️ Installation Guide

### 🔹 1. Setting Up the Arduino Input Bridge

1. Install **Arduino Legacy IDE 1.8.19**.
2. Install the **USB Host Shield 2.0** library and **HID-Project** by NicoHood from the Arduino Library Manager.
3. Open `firmware/mouse/mouse.ino` and upload it to your **Arduino Leonardo**.

The firmware forwards standard left, right, middle, back (Mouse 4) and forward (Mouse 5) button inputs, plus movement and scrolling. It reads button bits from the first byte of the mouse report and handles the project's 8-byte movement layout. Test the side buttons in Windows (for example, in a browser). The sketch must be uploaded again after any firmware change.

### 🔹 2. Installing Dependencies

1. Install **Python 3.9.10** (recommended) or later.
2. Install a recent NVIDIA driver. A separate CUDA Toolkit installation is not required when using the CUDA-enabled PyTorch wheel.
3. Install **PyTorch** with CUDA 12.8 support (recommended for RTX 50-series GPUs):

   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
   ```

4. Install the YOLOv8 runtime and application dependencies:

   ```bash
   pip install ultralytics opencv-python numpy pandas pyserial pywin32 keyboard termcolor PyQt6
   ```

### 🔹 3. Detection Models

The GUI and standalone engine load YOLO `.pt` weights with Ultralytics and run inference at `imgsz=640`.

- The **Detection model** picker lists `.pt` and `.engine` files in `v/scripts` and Downloads. **Browse** can select another file.
- Saved relative model names are resolved against these folders at startup, so existing settings keep working if they stored only a filename.
- Changing the model while running loads the new one on the inference thread. Inference pauses briefly during the load, and a failed selection leaves the previous model active.
- On CUDA, `.pt` inference requests FP16 and cuDNN benchmarking. TensorRT `.engine` precision is fixed at export. Both use 640-pixel inference and cap post-NMS detections.
- The engine requests **Normal** Windows process priority (not High). A failure is shown in the status message.
- No YOLOv5 checkout or root `requirements.txt` is needed.

**Converting weights to TensorRT:** drag a `.pt` file onto `v/scripts/convert_pt_to_engine.bat`. It uses the project `.venv` and exports a 640-pixel FP16 TensorRT `.engine` next to the weights. Intermediate `.onnx` files are removed after the attempt. TensorRT, ModelOpt, Ultralytics and CUDA-enabled PyTorch must be installed in that environment, and engines must be exported for the target GPU and a compatible TensorRT/CUDA setup. If an engine with the same name exists, the script asks before replacing it. Afterwards, pick the `.engine` in the **Detection model** picker (use **Refresh** if needed).

### Native C++ / CUDA / TensorRT engine

The native assistant lives in `native/` and reuses `disabledassistance_config.json` (confidence values stored as 0–100 are converted to 0–1). The PyQt control panel selects the engine backend in `_create_engine()`: it uses the native binary when it has been built and falls back to the original Python engine otherwise, so the app always starts.

Every backend uses documented, user-space APIs. Nothing injects into another process, installs a kernel driver, or modifies the game or its anti-cheat.

The loader accepts both `.engine` layouts: a **raw TensorRT plan** (starts with the `ftrt` magic, e.g. `The Finals120k.engine`) and an **Ultralytics-wrapped plan** (a JSON metadata header, then the plan, then a trailer, e.g. `best V8s.engine`). The wrapped header is detected by its leading length, by the plan magic, or by the trailing length, so either format loads without conversion. Models must be static batch-1 YOLO engines with FP32 `[1,3,H,W]` input; the output may be `[1,4+classes,anchors]` or `[1,anchors,4+classes]`, with or without an objectness term, and single-class `[N,6]` xyxy rows are also understood.

#### Selectable backends

Capture and output are behind interfaces (`capture_backend.hpp`, `input_provider.hpp`), so either can be changed without touching the tracking or inference code. Both are chosen in the GUI, and the engine reports which one is active and falls back explicitly if the requested one cannot start.

| Setting | Values | Notes |
|---|---|---|
| `capture_backend` | `dxgi` (default), `gdi`, `synthetic` | `dxgi` = Desktop Duplication + CUDA interop, frames stay on the GPU. `gdi` = BitBlt, widest compatibility. `synthetic` = deterministic pattern for tests, no screen access. |
| `input_backend` | `arduino` (default), `simulated` | `arduino` drives the real USB HID bridge over serial. `simulated` records intended movement without moving any device, for tests and previews. |

`dxgi_capture.cpp` keeps the desktop texture on the GPU and copies only the FOV crop straight into a CUDA buffer, so no pixel data crosses the PCIe bus. A lost device or display-mode change rebuilds the duplication interface rather than failing the session.

The `synthetic` capture plus `simulated` output let the whole pipeline — preprocessing, inference, decoding, tracking, movement shaping, telemetry — run in automated tests with no game, no desktop capture, and no hardware.

The Arduino bridge runs at **115200 baud** (previously 9600, where an 8-byte packet occupied the wire for ~8 ms and set a hard floor on reaction time). The packet format is unchanged, so the firmware, the Python engine and the native serial bridge move together; re-upload `firmware/mouse/mouse.ino` after updating.

#### Targeting and movement

Targeting uses a 2D **Kalman filter** (`kalman.hpp`) for smoothing and lead prediction, and an **adaptive distance-scaled gain** in `movement_step`: the aim moves decisively when far from the target and collapses to fine control when close, so the crosshair settles instead of oscillating.

`movement.hpp` adds an optional **accessibility movement shaper** that bounds the per-frame step, eases the speed in and out, accumulates sub-pixel remainders so small corrections are not lost, and clears momentum inside a stop tolerance so the aim cannot orbit the target. It is deterministic, fully disableable (`movement_smoothing_enabled`), and is a comfort/controllability feature — not a scheme to disguise automated movement.

#### Training-data collection

`dataset.hpp` optionally records captured frames with their detections while you play, producing a labelled dataset in the YOLO text format (`images/`, `labels/`, `manifest.csv`, `labels.csv`). Training itself is deliberately not done in the real-time loop; this produces the labelled data a separate training pass needs. Disk writes happen on a background thread through a bounded queue that drops the oldest frame first, so a slow disk can never stall capture. Only the FOV crop is stored and nothing is uploaded.

#### Diagnostics

| Tool | Purpose |
|---|---|
| `native_engine_probe <model.engine>` | Reports engine layout, tensors, and dtypes without running the pipeline. |
| `native_engine_infer_probe <model.engine> [w h]` | Per-stage inference timings and resolved output layout. |
| `native_detect_image <model.engine> <image.ppm> [conf] [--annotate out.ppm]` | Runs one image through the real inference path and lists detections. Needs no game or screen. |
| `native_targeting_test` | Target selection, tracking, and Kalman behaviour. |
| `native_movement_test` | Movement shaper bounds, convergence, anti-oscillation, and dataset label formatting. |

Build (Ninja, after Visual Studio Build Tools, CUDA, and the TensorRT C++ SDK are installed):

```bat
call "C:\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64
cmake -S native -B native\build-ninja -G Ninja -DCMAKE_BUILD_TYPE=Release -DTENSORRT_ROOT="C:\path\to\TensorRT-11.3.0.99" -DCUDAToolkit_ROOT="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.1" -DCMAKE_CUDA_COMPILER="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.1\bin\nvcc.exe"
cmake --build native\build-ninja --target native_engine native_targeting_test native_engine_infer_probe
native\build-ninja\native_targeting_test.exe
native\build-ninja\native_engine.exe disabledassistance_config.json
```

`native_engine_infer_probe <model.engine>` reports the resolved output layout and per-stage inference timings without touching the screen or serial port, which is the quickest way to check a new model.

`native_engine.exe --frames 120` captures a short telemetry run and exits. CSV samples are written to `logs/` from the working directory. This path does not replace the PyQt control panel yet.

---

## 🧪 Tests

Run the Python suites with the project interpreter (any of them exits non-zero on failure):

```bat
.venv\Scripts\python.exe tests\test_config_compat.py
.venv\Scripts\python.exe tests\test_targeting_priority.py
.venv\Scripts\python.exe tests\test_gui_layout.py
.venv\Scripts\python.exe tests\test_gui_smoke.py
```

| Test | What it covers |
|---|---|
| `test_config_compat.py` | Profile library round-trips, the legacy `trigger_key` alias, 0–100 confidence storage, sanitising a damaged file. |
| `test_targeting_priority.py` | The five target-priority modes and the stickiness margin, using shared vectors. |
| `test_gui_layout.py` | Shell structure, grouped navigation, hit-target sizes, every page building — objectively, on the offscreen Qt platform. |
| `test_gui_smoke.py` | The real window starting, page switching, keyboard mode, profiles, and zero Qt stylesheet warnings. |

The native equivalents run without a GPU:

```bat
native\build-ninja\native_targeting_test.exe
native\build-ninja\native_movement_test.exe
```

`native_targeting_test` covers the same priority-mode vectors as the Python suite, so the two engines can be shown to rank targets identically.

---

## 🖱️ GUI Control Panel

A desktop control panel wraps the same detection engine as `disabledassistance.py`. Launch it, review your settings, then press **Start**. **Stop** and **Start** control the engine without opening a second process.

```bash
start.bat
```

The launcher uses the project `.venv` when available, otherwise `python` from PATH. It installs `opencv-python` if missing and checks that the interpreter has a Qt binding before opening the GUI. Install all dependencies, including PyQt6 and the CUDA-enabled PyTorch build, into that same environment. To install the GUI binding separately, run `python -m pip install PyQt6` with the interpreter that launches the GUI.

The GUI is a responsive PyQt6/PySide6 dark control center styled with the shared `theme.py` design system. It opens maximized with a grouped navigation rail, a page header with per-page actions, spacious settings pages, a live telemetry rail and persistent engine controls. The window is a three-column shell — a fixed 240px navigation rail, a flexible content column and a fixed 320px inspector — so only the content grows when the window is resized and nothing clips from 1024×680 upward.

The **Aim** page opens with a short **Quick setup** section for search area, aim point, movement response and staying on one target. **Show all aim controls** reveals the existing detailed movement, prediction, tracking and filter settings; none are removed. The status banner distinguishes no model detections, detections outside the FOV, confidence rejections, and waiting for a held target to reappear.

There is no separate **Overview** page: the live figures that used to live there are a persistent **status banner** pinned under the header, so the numbers stay visible while you tune any page.

**Settings pages**, grouped in the rail:

| Group | Pages |
|---|---|
| Workspace | Detection, Targeting, Response |
| Library | Display, Profiles, Models, Dataset |
| System | Device, Accessibility |

**Shortcuts:** **Ctrl+S** save settings · **Ctrl+R** refresh models and serial devices · **Ctrl+F** jump to model selection · **Ctrl+Q** emergency stop · **Esc** cancel the current action.

Settings are saved in `disabledassistance_config.json` and loaded automatically on startup.

### Targeting

The **Targeting** page controls how a target is chosen and how firmly it is held.

- **Lock smoothness** (1–10) — controls how quickly the crosshair closes the remaining gap while Lock is held. 1.0 applies the full correction; larger values ease toward the target. It works with both hard and normal lock modes.
- **Movement response** is normalized to 1–20 (1 is fastest). Older saved values below 1 are treated as 1, and each legacy movement step is bounded by the remaining aim error to prevent overshooting and oscillating across a target.
- **Target priority** — the ranking rule used when a new target must be picked: **Centre first** (nearest to the crosshair), **Confidence** (most certain detection), **Distance** (largest detection), **Hybrid** (confidence weighted by closeness to centre) or **Sticky** (hold the current target longest). The same modes exist in both the Python and native engines and are unit-tested against shared vectors.
- **Focus one target before switching** — the engine keeps the target it is already tracking even when another detection is close, so two nearby boxes cannot fight over the crosshair every frame.
- **Visible preview controls** — confidence and pixel distance can be shown per detection; the centre marker has cross, dot, circle, and combined styles, a custom colour/size, and an optional rainbow annotation cycle. These are ordinary visible preview annotations only.
- **Inference only while aiming** — an opt-in setting pauses model calls while the Lock input is released, then resumes on the next held frame. Capture and the visible preview remain active. Detection FPS limiting and independently paced preview remain available.
- **Stickiness** (0–4) — how much better a rival must be before the held target is given up. 0 switches immediately; 4 holds unless the current target is badly beaten.
- **Tracking-loss recovery** — **Grace period** is how long a target is remembered after its last detection (0–2000 ms) and **re-acquire radius** is how far a new detection may appear from the lost centre and still count as the same target.
- While the lock input is held, a temporary target-match miss now preserves the last target reference through the lock grace period instead of immediately jumping to a distant rival.
- While firing with Lock held, target association allows for larger camera/recoil displacement. Preview annotation is only rendered at the preview cadence, keeping it out of the detection hot path.

### Per-game profiles

The **Profiles** page saves the whole detection, targeting and response setup under a name, so switching game is one selection rather than re-tuning every slider. Profiles are stored in the same `disabledassistance_config.json` under a `profiles` block, with `active_profile` naming the one in use. The flat settings keys remain the live source of truth for the engine, so an older build that knows nothing about profiles still reads the file correctly. Applying a profile merges over the current settings, so a profile saved before a new option existed inherits the current value rather than clearing it.

### Model tools

The **Model** dropdown is filled directly from the `models/` folder, not from a list baked into the code: every `.engine`, `.onnx` and `.pt` weight found there is offered, with `.engine` (the native path) listed first. Drop a file into `models/` and press **Refresh** on the field to pick it up without restarting; **Browse…** still allows a weight kept elsewhere on disk.

The **Models** page lists the local model library and hosts the **TensorRT converter**. Choose a `.pt` or `.onnx` file and press **Convert to engine**; the existing `v/scripts` converter runs in a child process and its output streams live into the page, so a multi-minute export cannot block the interface. A conversion that fails leaves the previous model in place.

### Accessibility

The **Accessibility** page gathers the controls that matter most for comfort and non-mouse use.

- **Keyboard-only navigation** — every control is reachable with Tab and activated with Enter; the focused control shows an accent focus border. Icon-only controls carry accessible names and tooltips.
- **Comfort shaping** — extra easing near the target on top of the aiming curve.
- **Capture-region calibration** — **Use primary display** sets the capture dimensions from the real display and centres the offsets; **Centre offsets** zeroes them without touching the size.
- **Quick menu shortcut** — record the chord that opens the compact aim panel.

### Quick-access aim menu

A compact (248px) frameless overlay for the controls reached mid-game: movement shaping, flick, prediction and action timing, plus Start/Stop and the live engine state. It is opened with a user-recordable shortcut (default **F8**), hides when it loses focus so it never sits over a game, and closing it never stops the session. Every control it shows is the same widget the main window uses, so the two can never disagree.

### Assist Profile Options

- Capture size, **screen resolution** and center offsets; square or circular guide with a saved colour
- **Screen resolution** is set either from a preset (`1080p`, `1440p`, `4K`, `720p`, `Ultrawide`) or with **Set custom res**, which exposes the `ScreenResX` / `ScreenResY` fields directly. The old `width` / `height` keys are still read on load, so no existing configuration is lost.
- Minimum and action-confidence thresholds, plus a 1–5 candidate detection limit
- **Lock** and **Shoot** bindings via **Record lock key** / **Record shoot input** (keyboard and mouse buttons supported, Escape cancels)
- Aim height, smoothness, aiming curve, prediction look-ahead, lock delay and click interval
- Local `.pt` / `.engine` model selection, Browse, and library rescan; model changes apply while running
- Serial device scan, port selection (or manual entry), and a test packet
- Optional click-through FOV guide and floating detection preview, with an always-on-top setting

### Telemetry

The telemetry rail and the status banner show engine status, current target, processing rate, and per-stage timing (rolling median / p95).

**CSV logging is off by default.** The loop is uncapped, so a per-frame log runs to hundreds of thousands of lines in minutes and the file never stops growing — it is a measurement tool, not something a normal session should pay for. Turn it on in **Dataset → Diagnostics → Write pipeline metrics to logs/**. When enabled, samples are rate-limited to 20 Hz and the file stops at a hard cap (200,000 rows or 24 MB) instead of growing without limit. Files land in `logs/pipeline_metrics_<UTC timestamp>.csv`.

### Idle back-off

When no target has been detected for about 45 frames, the engine holds a configurable **idle frame rate** (default 20 fps) instead of running flat out, so an empty screen — the desktop, a menu, or a game that isn't running — costs a fraction of the CPU and GPU time. The first accepted target restores full speed immediately. Adjust it in **Dataset → Diagnostics**; disable it by unchecking *Slow down when no target is visible*.

Pipeline telemetry records capture, frame preparation, the model prediction call, result transfer/decoding, target processing/output, preview submission, capture-to-detection time, and capture-to-preview-submission time. Raw per-frame samples are buffered and flushed periodically. CUDA prediction may be asynchronous, so GPU completion and synchronization time can appear under result transfer/decoding rather than the prediction call. No screenshots or frame pixels are written to the CSV.

---

## 🎮 How To Use

1. Run `start.bat`.
2. Open **Device** and select your Arduino from the scanned serial ports (or type a port name). Use **Scan** or **Ctrl+R** to rescan. Changing the port reconnects the serial device.
3. Open **Detection**, set your display dimensions, and press **Start**.
4. Hold the **Lock key** for movement correction and the **Shoot input** to enable automated clicks.
5. To run without the GUI, use `python disabledassistance.py` with the engine's default settings.

**Recommended setup for consistent results:**

- Use the same Windows mouse sensitivity and in-game sensitivity across all players in a match so assistance behaves identically.
- Run the game in **windowed fullscreen** for best capture performance.
- Render targets in a **distinct, high-contrast colour** so the detection model can separate them reliably. Match this to the colour your model was trained on.

The engine does not save a screenshot on every iteration. Frame rate is not capped by a fixed loop delay. Actual speed depends on capture, model inference, hardware and capture size.

---

## 🗺️ Roadmap

- [ ] Define game modes (e.g. duels, team objectives, time trials)
- [ ] Standardised assist-profile limits for ranked parity
- [ ] In-game profile display so opponents can see each other's assist settings
- [ ] Built-in assistance integration (replace external screen capture with direct game hooks you control)
- [ ] Accessibility options beyond aiming: input remapping, one-handed layouts, adjustable timing windows
- [ ] Matchmaking and lobbies
- [ ] Playtesting with disabled players and community feedback

---

## 🤝 Contributing

Contributions are welcome, especially from players with disabilities and accessibility specialists. Fork the repository, improve it and open a pull request. Feedback on assist-profile design and fairness rules is as valuable as code.

---

## 🙏 Credits

This project builds on an open-source object-detection assist engine. The original author and project are credited here: **[add original repository name and link]**.

---

## 📜 License

Released under the **GNU General Public License v3.0**. See the [LICENSE](LICENSE) file for details. As a derivative work, this project must retain the original copyright notices and license terms.
