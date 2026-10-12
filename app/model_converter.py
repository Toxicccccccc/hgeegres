"""Run the project's TensorRT export scripts from the GUI.

This is a thin, Qt-free wrapper around the existing converters in
``v/scripts`` so the control center can offer a **Model converter** page without
duplicating the export logic. It deliberately reuses those scripts rather than
re-implementing the export:

* ``convert_pt_to_engine.py``   -- ``.pt``  -> ``.engine`` (640px FP16)
* ``convert_onnx_to_engine.py`` -- ``.onnx`` -> ``.engine``

Why a subprocess and not an import?

* The converters import PyTorch, TensorRT, Ultralytics and ModelOpt. Those are
  heavyweight and, more importantly, they must run in the *same* environment
  that has CUDA-enabled PyTorch -- which may not be the environment running the
  GUI. Running the script through ``sys.executable`` keeps the current
  interpreter's environment (the project ``.venv`` when launched from
  ``start.bat``) and lets us stream its stdout for a live log.
* A conversion can take minutes and load multi-GB libraries; running it in a
  child process means a crash or an OOM cannot take the GUI down with it.

The class is a plain object with a ``run()`` iterator-free interface so the GUI
can pump ``poll()`` from a ``QTimer`` on its own thread, and the work itself can
be driven from a ``QThread`` worker. It never blocks the GUI thread.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The converters live under tools/ in this project. They used to be looked up
# under `v/scripts/` relative to the app/ folder (i.e. app/v/scripts/...), a path
# that does not exist here -- so validate() always reported "Converter script
# missing" and the Models page Convert button never ran. The scripts are now
# resolved from the real project root.
CONVERTERS = {
    "pt": {
        "script": ROOT / "tools" / "convert_pt_to_engine.py",
        "label": "YOLO .pt weights",
        "suffixes": (".pt",),
        "output_suffix": ".engine",
    },
    "onnx": {
        "script": ROOT / "tools" / "convert_onnx_to_engine.py",
        "label": "ONNX model",
        "suffixes": (".onnx",),
        "output_suffix": ".engine",
    },
}


def converter_for_path(path: Path | str) -> str | None:
    """Return the converter key that handles ``path``'s extension, if any."""
    suffix = Path(path).suffix.lower()
    for key, spec in CONVERTERS.items():
        if suffix in spec["suffixes"]:
            return key
    return None


def output_path_for(path: Path | str) -> Path:
    """Where the converter writes its engine: beside the source, same stem."""
    source = Path(path)
    return source.with_suffix(".engine")


class ConversionJob:
    """One converter subprocess with a bounded, polled log buffer.

    Usage from the GUI::

        job = ConversionJob(source_path, overwrite=True)
        job.start()
        # from a QTimer on the GUI thread:
        for line in job.drain():
            append_to_log(line)
        if job.finished:
            report(job.return_code)
    """

    # Keep the log bounded so a chatty export cannot grow memory without limit;
    # the oldest lines are dropped from the tail we still hold, but the GUI log
    # widget keeps whatever it has already displayed.
    MAX_BUFFERED_LINES = 4000

    def __init__(self, source_path: Path | str, overwrite: bool = False):
        self.source = Path(source_path)
        self.overwrite = overwrite
        self.kind = converter_for_path(self.source)
        self.output = output_path_for(self.source)
        self._process: subprocess.Popen | None = None
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self.return_code: int | None = None
        self.error: str | None = None
        self._started = False

    # -- lifecycle ---------------------------------------------------------
    @property
    def started(self) -> bool:
        return self._started

    @property
    def finished(self) -> bool:
        """True once the child has exited and its output has been drained.

        The reader thread must have exited as well, otherwise ``drain`` could
        observe an empty buffer while the pump still holds the last lines, and
        the GUI would report completion with output still missing.
        """
        if not (self._started and self._process is not None and self._process.poll() is not None):
            return False
        reader = self._reader
        return reader is None or not reader.is_alive()

    @property
    def running(self) -> bool:
        return self._started and not self.finished

    def validate(self) -> str | None:
        """Return a human-readable problem, or ``None`` when the job is runnable."""
        if self.kind is None:
            return (
                f"{self.source.name} is not a supported input. "
                "Choose a .pt or .onnx file."
            )
        if not self.source.is_file():
            return f"File not found: {self.source}"
        if not CONVERTERS[self.kind]["script"].is_file():
            return f"Converter script missing: {CONVERTERS[self.kind]['script']}"
        return None

    def start(self) -> bool:
        """Launch the converter. Returns False (with ``.error`` set) on failure."""
        problem = self.validate()
        if problem:
            self.error = problem
            return False

        command = [sys.executable, str(CONVERTERS[self.kind]["script"]), str(self.source)]
        if self.overwrite:
            command.append("--overwrite")

        creationflags = 0
        if sys.platform == "win32":
            # Never pop a console window; the GUI shows the stream itself.
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            self.error = f"Could not start the converter: {exc}"
            return False

        self._started = True
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        return True

    def _pump(self) -> None:
        """Read the child's output on a background thread into the buffer."""
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw in process.stdout:
            with self._lock:
                self._lines.append(raw.rstrip("\r\n"))
                if len(self._lines) > self.MAX_BUFFERED_LINES:
                    del self._lines[: len(self._lines) - self.MAX_BUFFERED_LINES]
        try:
            process.wait()
        except OSError:
            pass
        self.return_code = process.returncode

    # -- polling -----------------------------------------------------------
    def drain(self) -> list[str]:
        """Return and clear the lines buffered since the last call."""
        with self._lock:
            lines = self._lines
            self._lines = []
        return lines

    def cancel(self) -> None:
        """Terminate the child. Safe to call when it is already finished."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            pass
