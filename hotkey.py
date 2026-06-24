"""Process-wide global hotkey via Carbon RegisterEventHotKey.

Works system-wide regardless of which app is focused, and needs no
Accessibility / Input-Monitoring permission (so it triggers no permission
prompt). The fired callback runs on the main thread, since Carbon shares the
Cocoa event loop.
"""

import ctypes
import ctypes.util


def _load_carbon():
    """The hotkey symbols live in HIToolbox; the Carbon umbrella alone doesn't
    re-export them on recent macOS. Try the known locations in order."""
    candidates = [
        "/System/Library/Frameworks/Carbon.framework/Versions/A/Frameworks/"
        "HIToolbox.framework/Versions/A/HIToolbox",
        "/System/Library/Frameworks/Carbon.framework/Carbon",
        ctypes.util.find_library("Carbon"),
    ]
    for path in candidates:
        if not path:
            continue
        try:
            lib = ctypes.cdll.LoadLibrary(path)
            lib.RegisterEventHotKey  # probe: raises if symbols are absent
            lib.InstallEventHandler
            return lib
        except (OSError, AttributeError):
            continue
    raise OSError("Could not load Carbon HIToolbox with hotkey symbols")


_carbon = _load_carbon()


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


# OSStatus handler(EventHandlerCallRef, EventRef, void* userData)
_HANDLER = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)

_kEventClassKeyboard = 0x6B657962  # 'keyb'
_kEventHotKeyPressed = 6

# Carbon virtual key codes (HIToolbox Events.h)
kVK_ANSI_L = 0x25

# Carbon modifier masks
cmdKey = 0x0100
shiftKey = 0x0200
optionKey = 0x0800
controlKey = 0x1000

# InstallApplicationEventHandler is a C macro, not an exported symbol; the real
# function is InstallEventHandler(target, handler, numTypes, list, data, outRef).
_carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
_carbon.InstallEventHandler.restype = ctypes.c_int32
_carbon.InstallEventHandler.argtypes = [
    ctypes.c_void_p,
    _HANDLER,
    ctypes.c_uint32,
    ctypes.POINTER(_EventTypeSpec),
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_carbon.RegisterEventHotKey.restype = ctypes.c_int32
_carbon.RegisterEventHotKey.argtypes = [
    ctypes.c_uint32,
    ctypes.c_uint32,
    _EventHotKeyID,
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_void_p),
]

# Keep callback + hotkey refs alive for the whole process; otherwise Python's
# GC frees the C callback and the next keypress crashes.
_refs = []


def register(callback, key_code=kVK_ANSI_L, modifiers=cmdKey | shiftKey):
    """Register a system-wide hotkey. `callback` takes no arguments.

    Returns True on success. The module must stay imported for the hotkey to
    persist. Default combo is Cmd+Shift+L.
    """

    def _trampoline(_next, _event, _user):
        try:
            callback()
        except Exception:
            pass
        return 0

    handler = _HANDLER(_trampoline)
    spec = _EventTypeSpec(_kEventClassKeyboard, _kEventHotKeyPressed)
    target = _carbon.GetApplicationEventTarget()

    if _carbon.InstallEventHandler(
        target, handler, 1, ctypes.byref(spec), None, None
    ) != 0:
        return False

    hotkey_id = _EventHotKeyID(0x4C594252, 1)  # signature 'LYBR'
    ref = ctypes.c_void_p()
    if _carbon.RegisterEventHotKey(
        key_code, modifiers, hotkey_id, target, 0, ctypes.byref(ref)
    ) != 0:
        return False

    _refs.append(handler)
    _refs.append(ref)
    return True
