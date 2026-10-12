import ctypes
from ctypes import wintypes

ACCENT_ENABLE_BLURBEHIND = 3
WCA_ACCENT_POLICY = 19

class ACCENTPOLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_int),
        ("AnimationId", ctypes.c_int)
    ]

class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t)
    ]

def enable_blur(hwnd: int):
    accent = ACCENTPOLICY()
    accent.AccentState = ACCENT_ENABLE_BLURBEHIND
    accent.GradientColor = 0xCC000000

    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.SizeOfData = ctypes.sizeof(accent)
    data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)

    set_window_composition_attribute = ctypes.windll.user32.SetWindowCompositionAttribute
    set_window_composition_attribute.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA)]
    set_window_composition_attribute.restype = wintypes.BOOL
    set_window_composition_attribute(hwnd, ctypes.byref(data))
