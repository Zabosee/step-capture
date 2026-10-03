"""Erkennung sensibler Kontexte (UAC, Admin-Fenster, Passwortfelder).

Nur unter Windows aktiv. Auf anderen Systemen meldet der Detektor immer "nicht sensibel".

Erkennungsebenen:
  1. Sicherer Desktop (klassische UAC-Abfrage): ``OpenInputDesktop`` schlägt fehl.
  2. Vordergrundfenster gehört zu consent.exe / credwiz.exe / LogonUI.exe usw.
     oder hat eine bekannte Fensterklasse / den Titel "Benutzerkontensteuerung".
  3. Fokussiertes Win32-Edit-Feld mit ES_PASSWORD-Stil (schnell, synchron).
  4. UI Automation (``IsPassword``) für Browser, WPF, UWP usw. (langsamer, nur im Poll-Thread).
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

SENSITIVE_PROCESSES = {
    "consent.exe", "credwiz.exe", "logonui.exe", "credentialuibroker.exe",
    "winlogon.exe", "securityhealthhost.exe",
}
SENSITIVE_CLASSES = {
    "credential dialog xaml host",
    "$$$secure uap dummy window class for interactive input desktop",
    "credential dialog",
}
SENSITIVE_TITLES = {"benutzerkontensteuerung", "user account control"}

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUITHREADINFO)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    _GWL_STYLE = -16
    _ES_PASSWORD = 0x0020
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _DESKTOP_SWITCHDESKTOP = 0x0100

    def _class_name(hwnd) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _window_text(hwnd) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value

    def _process_name(pid: int) -> str:
        """exe-Name klein geschrieben; leer, wenn kein Zugriff."""
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def _secure_desktop_active() -> bool:
        """Auf dem sicheren Desktop (UAC) ist OpenInputDesktop für uns nicht erlaubt."""
        desk = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
        if not desk:
            return True
        user32.CloseDesktop(desk)
        return False


class SensitiveContextDetector:
    """Prüft, ob gerade ein sensibler Kontext aktiv ist (dann darf nichts aufgezeichnet werden)."""

    def __init__(self) -> None:
        self._own_pid = os.getpid()
        self._uia_failed = False
        self._uia_thread: "threading.Thread | None" = None
        self._uia_lock = threading.Lock()
        self._uia_value = False
        self._uia_stamp = 0.0
        self.reason = ""             # Auslöser der letzten Erkennung (für das Log)

    # -- schnelle Prüfung (darf in Eingabe-Callbacks laufen) ------------------
    def is_sensitive_fast(self) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            if _secure_desktop_active():
                self.reason = "sicherer Desktop (UAC)"
                return True
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            cls, title = _class_name(hwnd), _window_text(hwnd)
            if cls.lower() in SENSITIVE_CLASSES:
                self.reason = f"Fensterklasse {cls!r}"
                return True
            if title.strip().lower() in SENSITIVE_TITLES:
                self.reason = f"Fenstertitel {title!r}"
                return True

            pid = wintypes.DWORD()
            tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value and pid.value != self._own_pid:
                name = _process_name(pid.value)
                if name in SENSITIVE_PROCESSES:
                    self.reason = f"Prozess {name}"
                    return True
                # Bewusst KEINE Pause für Admin-Fenster an sich: nach der UAC-Bestätigung
                # läuft z. B. ein Installer mit Adminrechten und soll aufgezeichnet werden.
                # Geschützt bleiben UAC/Anmeldedialoge und Passwortfelder.

            info = _GUITHREADINFO()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetGUIThreadInfo(tid, ctypes.byref(info)) and info.hwndFocus:
                if _class_name(info.hwndFocus).lower() == "edit":
                    if user32.GetWindowLongW(info.hwndFocus, _GWL_STYLE) & _ES_PASSWORD:
                        self.reason = "Passwortfeld (ES_PASSWORD)"
                        return True
        except Exception:  # im Zweifel lieber schützen als mitschneiden
            log.exception("Sicherheitsprüfung (schnell) fehlgeschlagen")
            self.reason = "Fehler in der Prüfung (fail-safe)"
            return True
        return False

    # -- vollständige Prüfung (nur im Poll-Thread, inkl. UI Automation) --------
    def is_sensitive(self) -> bool:
        if self.is_sensitive_fast():
            return True
        if self._uia_result_fresh():
            self.reason = "Passwortfeld (UI Automation)"
            return True
        return False

    # UI Automation kann bei einem beschäftigten/hängenden Zielprogramm (z. B. einem
    # gerade startenden Installer) sehr lange blockieren. Deshalb läuft die Abfrage in
    # einem eigenen Thread; der Poll-Thread liest nur das letzte Ergebnis und bleibt
    # dadurch immer reaktionsfähig.
    _UIA_MAX_AGE = 1.0

    def _uia_result_fresh(self) -> bool:
        if not IS_WINDOWS or self._uia_failed:
            return False
        if self._uia_thread is None:
            self._uia_thread = threading.Thread(target=self._uia_loop, daemon=True)
            self._uia_thread.start()
        with self._uia_lock:
            value, stamp = self._uia_value, self._uia_stamp
        return value and (time.monotonic() - stamp) <= self._UIA_MAX_AGE

    def _uia_loop(self) -> None:
        try:
            import uiautomation as auto
        except Exception:
            log.warning("Paket 'uiautomation' nicht ladbar – Passwortfelder in Browsern/WPF "
                        "werden nicht erkannt.", exc_info=True)
            self._uia_failed = True
            return
        with auto.UIAutomationInitializerInThread():
            while True:
                try:
                    control = auto.GetFocusedControl()
                    value = bool(control is not None and control.Element.CurrentIsPassword)
                except Exception:
                    log.debug("UIA-Abfrage fehlgeschlagen", exc_info=True)
                    value = False
                with self._uia_lock:
                    self._uia_value, self._uia_stamp = value, time.monotonic()
                time.sleep(0.1)
