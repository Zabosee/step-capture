"""Ermittelt per UI Automation, worauf geklickt wurde (Elementname, Typ, Fenstertitel).

UI Automation kann bei beschäftigten Zielprogrammen lange blockieren. Deshalb läuft die
Abfrage in einem eigenen Thread; der Aufrufer wartet nur begrenzt auf das Ergebnis.
"""
from __future__ import annotations

import contextlib
import logging
import queue
import sys
import threading
import time
from concurrent.futures import Future
from typing import Optional, Tuple

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

TYPE_NAMES = {
    "ButtonControl": "Schaltfläche", "EditControl": "Eingabefeld",
    "MenuItemControl": "Menüeintrag", "MenuControl": "Menü", "MenuBarControl": "Menüleiste",
    "TabItemControl": "Registerkarte", "CheckBoxControl": "Kontrollkästchen",
    "RadioButtonControl": "Optionsfeld", "HyperlinkControl": "Link",
    "ListItemControl": "Listeneintrag", "ListControl": "Liste",
    "ComboBoxControl": "Auswahlfeld", "TreeItemControl": "Baumeintrag",
    "DataItemControl": "Tabellenzeile", "SplitButtonControl": "Schaltfläche",
    "TextControl": "Text", "ImageControl": "Bild", "ToolBarControl": "Symbolleiste",
    "SliderControl": "Schieberegler", "ScrollBarControl": "Bildlaufleiste",
    "TitleBarControl": "Titelleiste", "DocumentControl": "Dokumentbereich",
    "PaneControl": "Bereich", "GroupControl": "Gruppe", "WindowControl": "Fenster",
    "TableControl": "Tabelle", "TabControl": "Registerkartenleiste",
    "HeaderItemControl": "Spaltenkopf", "ToolTipControl": "Kurzinfo",
    "SpinnerControl": "Zahlenfeld", "ProgressBarControl": "Fortschrittsbalken",
}
MAX_NAME_LEN = 80
STUCK_SECONDS = 1.5


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_NAME_LEN else text[:MAX_NAME_LEN - 1] + "…"


def describe_point(auto, x: int, y: int) -> Optional[str]:
    """Beschreibung des Elements bei (x, y), z. B. "Schaltfläche „Weiter“ im Fenster „Setup“"."""
    control = auto.ControlFromPoint(x, y)
    if control is None:
        return None
    type_name = control.ControlTypeName or ""
    kind = TYPE_NAMES.get(type_name, "Element")
    is_password = False
    with contextlib.suppress(Exception):
        is_password = bool(control.Element.CurrentIsPassword)
    if is_password:
        return "Passwortfeld"                    # nie Namen/Inhalt eines Passwortfelds auslesen

    name = _clip(control.Name)
    window = ""
    with contextlib.suppress(Exception):
        top = control.GetTopLevelControl()
        if top is not None:
            window = _clip(top.Name)

    if name and name != window:
        text = f"{kind} „{name}“"
    elif type_name == "WindowControl" and name:
        text = f"Fenster „{name}“"
    else:
        text = kind
    if window and window != name:
        text += f" im Fenster „{window}“"
    return text


class TargetResolver:
    """Beantwortet Abfragen (x, y) → Beschreibung in einem eigenen UI-Automation-Thread."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[Optional[Tuple[int, int, Future]]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._failed = not IS_WINDOWS
        self._busy_since: Optional[float] = None     # gesetzt, solange eine Abfrage läuft

    def submit(self, x: int, y: int) -> "Future[Optional[str]]":
        fut: "Future[Optional[str]]" = Future()
        busy = self._busy_since
        if self._failed or (busy is not None and time.monotonic() - busy > STUCK_SECONDS):
            fut.set_result(None)                 # Zielprogramm hängt: nicht auch noch warten
            return fut
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        self._queue.put((x, y, fut))
        return fut

    def close(self) -> None:
        self._queue.put(None)

    def _loop(self) -> None:
        try:
            import uiautomation as auto
            init = auto.UIAutomationInitializerInThread()
        except Exception:
            log.warning("UI Automation nicht verfügbar – Klickziele werden nicht ermittelt.")
            self._failed = True
            self._drain()
            return
        with init:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                x, y, fut = item
                self._busy_since = time.monotonic()
                try:
                    fut.set_result(describe_point(auto, x, y))
                except Exception:
                    log.debug("Klickziel konnte nicht ermittelt werden", exc_info=True)
                    fut.set_result(None)
                finally:
                    self._busy_since = None

    def _drain(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if item:
                item[2].set_result(None)
