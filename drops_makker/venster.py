"""Het browservenster helemaal verbergen op Windows, ook uit de taakbalk.

Zo staat er geen tweede Chrome naast je eigen Chrome. Het venster wordt
gevonden aan een unieke titel die drops-makker even op de eerste pagina zet.
"""
import ctypes
import sys

SW_HIDE, SW_SHOWNORMAL = 0, 1

if sys.platform == "win32":
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]


def kan_verbergen():
    return sys.platform == "win32"


def zoeken(titel_begin):
    """Het eerste venster waarvan de titel zo begint, of None."""
    gevonden = []

    @_EnumWindowsProc
    def langs(hwnd, _):
        n = _user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            _user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith(titel_begin):
                gevonden.append(hwnd)
                return False
        return True

    _user32.EnumWindows(langs, 0)
    return gevonden[0] if gevonden else None


def verbergen(hwnd):
    _user32.ShowWindow(hwnd, SW_HIDE)


def tonen(hwnd):
    _user32.ShowWindow(hwnd, SW_SHOWNORMAL)
    _user32.SetForegroundWindow(hwnd)


def zichtbaar(hwnd):
    return bool(_user32.IsWindowVisible(hwnd))
