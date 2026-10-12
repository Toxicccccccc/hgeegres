"""
Optional detection stream reader (shared memory).

The C++ backend publishes the current frame's detections into a named Windows
file mapping; this reader OPENS the same region (read-only) and decodes it so the
overlay can draw real boxes. If the backend is not publishing (the mapping does
not exist yet, or is zeroed), every call returns None and the overlay simply
shows the FOV / crosshair. Nothing here ever raises into the UI.

IMPORTANT: this reader must only *open* an existing mapping, never *create* one.
Python's ``mmap`` with a ``tagname`` will silently CREATE the named section if it
doesn't exist, and it does so as PAGE_READONLY. If the overlay is started before
the backend, that pre-created read-only section makes the backend's writable
``MapViewOfFile`` fail, so it can never publish. Using ``OpenFileMappingW`` via
ctypes avoids creating anything, so launch order no longer matters.

Wire format (little-endian), see backend/detection_stream.h:

    Header (32 bytes):
        uint32 magic   = 0x4C554E32  ('LUN2')
        uint32 version = 1
        uint32 seq                # bumped on every publish
        int32  frameW, frameH     # net capture size (e.g. 256)
        int32  count              # number of records that follow
        uint32 reserved[2]

    Record (24 bytes) * count (max 64):
        float32 x1, y1, x2, y2    # CROSSHAIR-ORIGIN coords: crosshair = (0,0)
        float32 conf
        int32   kind              # 0=detection 1=locked 2=predicted
"""

import ctypes
from ctypes import wintypes
import struct

SHM_NAME = "LunarV2DetStream"
MAGIC = 0x4C554E32
VERSION = 1
MAX_RECORDS = 64
HEADER_SIZE = 32
RECORD_SIZE = 24
SHM_SIZE = 4096

KIND_DETECTION = 0
KIND_LOCKED = 1
KIND_PREDICTED = 2

_FILE_MAP_READ = 0x0004

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_OpenFileMapping = _kernel32.OpenFileMappingW
_OpenFileMapping.restype = wintypes.HANDLE
_OpenFileMapping.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]

_MapViewOfFile = _kernel32.MapViewOfFile
_MapViewOfFile.restype = ctypes.c_void_p
_MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                           wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]

_UnmapViewOfFile = _kernel32.UnmapViewOfFile
_UnmapViewOfFile.restype = wintypes.BOOL
_UnmapViewOfFile.argtypes = [ctypes.c_void_p]

_CloseHandle = _kernel32.CloseHandle
_CloseHandle.restype = wintypes.BOOL
_CloseHandle.argtypes = [wintypes.HANDLE]


class DetectionStream:
    def __init__(self):
        self._handle = None
        self._view = None
        self._open()

    def _open(self):
        """Open the existing mapping (never create it)."""
        try:
            handle = _OpenFileMapping(_FILE_MAP_READ, False, SHM_NAME)
            if not handle:
                return
            view = _MapViewOfFile(handle, _FILE_MAP_READ, 0, 0, SHM_SIZE)
            if not view:
                _CloseHandle(handle)
                return
            self._handle = handle
            self._view = view
        except OSError:
            self._handle = None
            self._view = None

    def available(self) -> bool:
        return self._view is not None

    def read(self):
        """Return a snapshot dict or None if no valid frame is published."""
        if self._view is None:
            self._open()
            if self._view is None:
                return None
        try:
            head = ctypes.string_at(self._view, HEADER_SIZE)
            magic, version, seq, fw, fh, count = struct.unpack_from("<IIIiii", head, 0)
            if magic != MAGIC or version != VERSION:
                return None
            count = max(0, min(count, MAX_RECORDS))

            boxes = []
            if count:
                blob = ctypes.string_at(self._view + HEADER_SIZE, count * RECORD_SIZE)
                for i in range(count):
                    off = i * RECORD_SIZE
                    x1, y1, x2, y2, conf, kind = struct.unpack_from("<fffffi", blob, off)
                    boxes.append((x1, y1, x2, y2, conf, kind))

            return {"seq": seq, "frameW": fw, "frameH": fh, "boxes": boxes}
        except (struct.error, ValueError, OSError):
            return None

    def close(self):
        if self._view is not None:
            try:
                _UnmapViewOfFile(self._view)
            except OSError:
                pass
            self._view = None
        if self._handle is not None:
            try:
                _CloseHandle(self._handle)
            except OSError:
                pass
            self._handle = None
