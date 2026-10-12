"""
Controls the Inchro C++ backend as a child process.

Start/stop are non-blocking so the Qt event loop stays responsive. Auth lines
prefixed with ``[AUTH]`` are parsed from stdout for login prompting.
"""

import json
import os
from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal, QEventLoop

AUTH_PREFIX = "[AUTH] "

EXIT_OK = 0
EXIT_LOGIN_FAILED = 1
EXIT_LOGGED_OUT = 2

_START_TIMEOUT_MS = 4000
_STOP_TERM_MS = 2000
_STOP_KILL_MS = 1500


class Backend(QObject):
    output = pyqtSignal(str)
    state_changed = pyqtSignal(bool)
    auth_event = pyqtSignal(str, str)
    finished_with_code = pyqtSignal(int)
    busy_changed = pyqtSignal(bool, str)       # busy, status message
    start_completed = pyqtSignal(bool, str)    # ok, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc: QProcess | None = None
        self._line_buf = ""
        self._user_stopped = False
        self._busy = False
        self._starting = False
        self._stopping = False
        self._ignore_next_finish = False
        self._start_timer: QTimer | None = None
        self._stop_kill_timer: QTimer | None = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    def is_busy(self) -> bool:
        return self._busy

    def start_async(self, exe_path: str) -> None:
        if self._busy:
            return
        if self.is_running():
            self.start_completed.emit(False, "Backend already running.")
            return
        if not exe_path or not os.path.isfile(exe_path):
            self.start_completed.emit(False, f"Inchro.exe not found at:\n{exe_path}")
            return

        self._user_stopped = False
        self._line_buf = ""
        self._starting = True
        self._set_busy(True, "Starting backend…")

        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(os.path.dirname(os.path.abspath(exe_path)))
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.setStandardInputFile(QProcess.nullDevice())
        self.proc.readyReadStandardOutput.connect(self._on_output)
        self.proc.finished.connect(self._on_finished)
        self.proc.errorOccurred.connect(self._on_error)
        self.proc.started.connect(self._on_started)

        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._on_start_timeout)
        self._start_timer.start(_START_TIMEOUT_MS)
        self.proc.start(exe_path, [])

    def stop(self) -> None:
        if not self.is_running() or self._busy:
            return
        self._user_stopped = True
        self._stopping = True
        self._set_busy(True, "Stopping backend…")
        self.proc.terminate()
        self._stop_kill_timer = QTimer(self)
        self._stop_kill_timer.setSingleShot(True)
        self._stop_kill_timer.timeout.connect(self._on_stop_kill_timeout)
        self._stop_kill_timer.start(_STOP_TERM_MS)

    def stop_and_wait(self, timeout_ms: int = 6000) -> None:
        if not self.is_running():
            return
        loop = QEventLoop()

        def on_state(running: bool):
            if not running:
                loop.quit()

        self.state_changed.connect(on_state)
        self.stop()
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        try:
            self.state_changed.disconnect(on_state)
        except TypeError:
            pass

    def was_user_stopped(self) -> bool:
        return self._user_stopped

    def write_auth_boot(self, exe_path: str, username: str, password: str) -> str:
        folder = os.path.dirname(os.path.abspath(exe_path))
        path = os.path.join(folder, "ui_auth.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"username": username, "password": password}, f)
        return path

    def _set_busy(self, busy: bool, message: str = ""):
        self._busy = busy
        self.busy_changed.emit(busy, message)

    def _clear_start_timer(self):
        if self._start_timer:
            self._start_timer.stop()
            self._start_timer = None

    def _disconnect_started(self):
        if self.proc:
            try:
                self.proc.started.disconnect(self._on_started)
            except TypeError:
                pass

    def _finish_start_failed(self, message: str):
        if not self._starting:
            return
        self._clear_start_timer()
        self._disconnect_started()
        self._starting = False
        proc = self.proc
        if proc and proc.state() != QProcess.ProcessState.NotRunning:
            self._ignore_next_finish = True
            proc.kill()
        else:
            self.proc = None
        self._set_busy(False, "")
        self.state_changed.emit(False)
        self.start_completed.emit(False, message)
        if not (proc and proc.state() != QProcess.ProcessState.NotRunning):
            self.finished_with_code.emit(EXIT_LOGIN_FAILED)

    def _on_started(self):
        if not self._starting:
            return
        self._clear_start_timer()
        self._disconnect_started()
        self._starting = False
        self._set_busy(False, "")
        self.state_changed.emit(True)
        self.start_completed.emit(True, "Backend started.")

    def _on_start_timeout(self):
        if not self._starting or not self.proc:
            return
        if self.proc.state() == QProcess.ProcessState.Starting:
            self.proc.kill()
        self._finish_start_failed("Timed out waiting for backend to start.")

    def _on_stop_kill_timeout(self):
        if not self.proc or self.proc.state() == QProcess.ProcessState.NotRunning:
            return
        self.proc.kill()
        if self._stop_kill_timer:
            self._stop_kill_timer.stop()
        self._stop_kill_timer = QTimer(self)
        self._stop_kill_timer.setSingleShot(True)
        self._stop_kill_timer.timeout.connect(self._on_stop_give_up)
        self._stop_kill_timer.start(_STOP_KILL_MS)

    def _on_stop_give_up(self):
        if self._stopping and self.is_running():
            self._stopping = False
            self._set_busy(False, "")
            self.output.emit("\n[backend] stop timed out\n")

    def _on_output(self):
        if not self.proc:
            return
        data = bytes(self.proc.readAllStandardOutput())
        text = data.decode("utf-8", errors="replace")
        if not text:
            return
        self.output.emit(text)
        self._line_buf += text
        while "\n" in self._line_buf or "\r" in self._line_buf:
            for sep in ("\r\n", "\n", "\r"):
                if sep in self._line_buf:
                    line, self._line_buf = self._line_buf.split(sep, 1)
                    self._handle_auth_line(line.strip())
                    break

    def _handle_auth_line(self, line: str):
        if not line.startswith(AUTH_PREFIX):
            return
        payload = line[len(AUTH_PREFIX):].strip()
        if payload == "need_login":
            self.auth_event.emit("need_login", "")
        elif payload == "session_expired":
            self.auth_event.emit("logout", "")
        elif payload.startswith("logged_in:"):
            self.auth_event.emit("logged_in", payload[len("logged_in:"):].strip())
        elif payload.startswith("login_failed:"):
            self.auth_event.emit("login_failed", payload[len("login_failed:"):].strip())

    def _on_finished(self, code: int, _status):
        if self._ignore_next_finish:
            self._ignore_next_finish = False
            self.proc = None
            return

        if self._starting:
            self._clear_start_timer()
            self._disconnect_started()
            self._starting = False
            self._set_busy(False, "")
            self.proc = None
            self.state_changed.emit(False)
            self.start_completed.emit(False, "Backend exited during startup.")
            self.finished_with_code.emit(int(code))
            return

        leftover = self._line_buf.strip()
        if leftover:
            self._handle_auth_line(leftover)
        self._line_buf = ""

        if self._stopping:
            self._stopping = False
            self._set_busy(False, "")

        self.state_changed.emit(False)
        self.finished_with_code.emit(int(code))
        self.proc = None

    def _on_error(self, err):
        if self._starting:
            msg = self.proc.errorString() if self.proc else str(err)
            self._finish_start_failed(f"Failed to start backend: {msg}")
            return
        self.output.emit(f"\n[backend error] {err}\n")
