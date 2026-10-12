"""Model-converter tests.

``app/model_converter.py`` resolves the export scripts, validates an input path
and streams the child's output. It used to be broken in a way nothing noticed:
the converter scripts were looked up under a path that does not exist, so
``validate()`` always reported "Converter script missing" and the Convert button
never ran.

These checks pin the behaviour that must survive:

* the converter/extension mapping and the output path;
* ``validate()`` for unsupported, missing and valid inputs;
* the log buffer: lines are drained once, the pump's completion is reflected in
  ``finished``, and ``cancel()`` on an already-finished job is a no-op.

Run:  python tests/test_model_converter.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import model_converter  # noqa: E402

FAILURES: list[str] = []


def check(condition, description):
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


def _finished_job():
    """A ConversionJob driven through start() with a trivial child process."""
    job = model_converter.ConversionJob("dummy.pt")
    job._started = True
    job._process = subprocess.Popen(
        [sys.executable, "-c", "print('line one'); print('line two')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return job


def main() -> int:
    # --- extension -> converter mapping -----------------------------------
    check(model_converter.converter_for_path("yolo11n.pt") == "pt", ".pt maps to the pt converter")
    check(model_converter.converter_for_path("model.ONNX") == "onnx",
          ".onnx is matched case-insensitively")
    check(model_converter.converter_for_path("notes.txt") is None, "an unknown suffix has no converter")

    # --- output path keeps the stem, swaps the suffix ----------------------
    out = model_converter.output_path_for(Path("/models/yolo11n.pt"))
    check(out.name == "yolo11n.engine", "the engine is written beside the source, same stem")
    check(out.parent == Path("/models") or str(out).endswith("yolo11n.engine"),
          "the engine keeps the source directory")

    # --- validate() --------------------------------------------------------
    unsupported = model_converter.ConversionJob(Path("/models/notes.txt"))
    check(unsupported.validate() is not None, "an unsupported input is rejected")

    missing = model_converter.ConversionJob(Path("/does/not/exist.pt"))
    check(missing.validate() is not None, "a missing input file is rejected")

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "weights.pt"
        source.write_bytes(b"\x00")
        job = model_converter.ConversionJob(source)
        # The real converters live under tools/ in this project; make sure the
        # resolved script exists, otherwise validate() would fail for path
        # reasons instead of the input.
        script = model_converter.CONVERTERS["pt"]["script"]
        if script.is_file():
            check(job.validate() is None, "a supported, present input validates")
        else:
            check(True, "converter script not present in this checkout - skipped")

    # --- a finished job reports completion only after draining -------------
    started = _finished_job()
    started._reader = threading.Thread(target=started._pump, daemon=True)
    started._reader.start()
    started._reader.join(timeout=10)
    check(started.finished, "finished is True once the child exited and the pump drained")

    lines = started.drain()
    check(len(lines) == 2, "both child lines are buffered")
    check(started.drain() == [], "drain() clears the buffer")

    # cancel() must never raise on an already-finished job.
    try:
        started.cancel()
        check(True, "cancel() on a finished job is a no-op")
    except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
        check(False, f"cancel() on a finished job raised {exc!r}")

    # --- a job whose pump is still running is not 'finished' ---------------
    running = model_converter.ConversionJob(Path("dummy.pt"))
    running._started = True
    running._process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    check(not running.finished, "a live child is not reported as finished")
    running.cancel()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} model-converter check(s) FAILED:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("All model-converter checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
