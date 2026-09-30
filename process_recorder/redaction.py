"""Schwärzt sensible Felder (Passwörter, PINs, Tokens, IBAN …) in Screenshots.

Per UI Automation werden sichtbare Eingabefelder gesucht, die entweder als Passwortfeld
markiert sind (``IsPassword``) oder deren Name/Kennung auf sensible Inhalte hindeutet.
Gelesen werden ausschließlich Name, Kennung und Rechteck – nie der Inhalt eines Feldes.

Wie beim Klickziel (target.py) läuft die Abfrage in einem eigenen Thread; der Aufrufer
wartet nur begrenzt. Bei Zeitüberschreitung oder Fehler wird ohne Schwärzung weitergemacht.
"""
from __future__ import annotations

import logging
import queue
import re
import sys
import threading
import time
from concurrent.futures import Future
from typing import Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

REDACT_TIMEOUT = 0.8         # so lange wartet ein Schritt maximal auf die Feldsuche
STUCK_SECONDS = 1.5          # hängt eine Abfrage länger, wird nicht mehr gewartet
PADDING = 2                  # Rand um das Feld in Pixeln
MIN_SIZE = 4                 # kleinere Rechtecke (Pixel) sind kein sichtbares Feld
REDACT_COLOR = (0, 0, 0)

Rect = Tuple[int, int, int, int]        # links, oben, rechts, unten (Bildschirmkoordinaten)

# Lange, eindeutige Begriffe: Teilstring-Treffer im zusammengezogenen Namen
# (fängt auch „txtPassword“, „api_key“, „CreditCardNumber“).
_LONG_TERMS = ("passwort", "passwd", "password", "kennwort", "secret", "geheim", "token",
               "apikey", "kreditkarte", "creditcard", "cardnumber", "kartennummer",
               "sicherheitscode", "securitycode")
# Kurze Begriffe: nur als eigenes Wort (sonst „Spinner“, „Pinterest“, „Pipeline“ …)
_SHORT_TERMS = {"pin", "pwd", "iban", "cvv", "cvc", "tan", "puk"}
_CAMEL = re.compile(r"(?<=[a-zäöü0-9])(?=[A-ZÄÖÜ])")
_SPLIT = re.compile(r"[^0-9a-zäöüß]+")


def is_sensitive_name(name: str = "", automation_id: str = "") -> bool:
    """True, wenn Name oder Kennung eines Eingabefeldes auf sensible Daten hinweist."""
    for text in (name, automation_id):
        if not text:
            continue
        words = [w for w in _SPLIT.split(_CAMEL.sub(" ", text).lower()) if w]
        if _SHORT_TERMS.intersection(words):
            return True
        compact = "".join(words)
        if any(term in compact for term in _LONG_TERMS):
            return True
    return False


def to_image_rects(rects: Iterable[Rect], monitor: dict, image_size: Tuple[int, int]
                   ) -> List[Rect]:
    """Rechtecke aus Bildschirmkoordinaten in Bildkoordinaten des Monitor-Screenshots.

    Zieht den Monitor-Offset ab (Mehrmonitor-Aufbau, auch negative Koordinaten), skaliert
    falls das Bild nicht die Monitorgröße hat, beschneidet auf das Bild und verwirft leere
    oder außerhalb liegende Rechtecke.
    """
    width, height = image_size
    mw, mh = monitor["width"], monitor["height"]
    sx = width / mw if mw else 1.0
    sy = height / mh if mh else 1.0
    out: List[Rect] = []
    for left, top, right, bottom in rects:
        l = (left - monitor["left"]) * sx
        t = (top - monitor["top"]) * sy
        r = (right - monitor["left"]) * sx
        b = (bottom - monitor["top"]) * sy
        if r - l < MIN_SIZE or b - t < MIN_SIZE:
            continue                              # zu klein für ein sichtbares Feld
        l, t = max(0, int(l) - PADDING), max(0, int(t) - PADDING)
        r, b = min(width, int(r + 0.999) + PADDING), min(height, int(b + 0.999) + PADDING)
        if r > l and b > t:                       # sonst liegt das Feld außerhalb des Bildes
            out.append((l, t, r, b))
    return out


def redact_image(img, rects: Iterable[Rect]):
    """Füllt die Rechtecke (Bildkoordinaten) schwarz; verändert und liefert ``img``."""
    from PIL import ImageDraw

    rects = list(rects)
    if rects:
        draw = ImageDraw.Draw(img)
        for l, t, r, b in rects:
            draw.rectangle((l, t, r - 1, b - 1), fill=REDACT_COLOR)
    return img


def find_sensitive_rects(auto_client) -> List[Rect]:
    """Rechtecke aller sichtbaren sensiblen Eingabefelder auf dem Desktop (Bildschirm-Pixel).

    ``auto_client`` ist ``uiautomation.uiautomation._AutomationClient.instance()``.
    Muss in einem Thread mit initialisiertem COM laufen.
    """
    core, ia = auto_client.UIAutomationCore, auto_client.IUIAutomation
    is_pwd = ia.CreatePropertyCondition(core.UIA_IsPasswordPropertyId, True)
    is_edit = ia.CreatePropertyCondition(core.UIA_ControlTypePropertyId,
                                         core.UIA_EditControlTypeId)
    visible = ia.CreatePropertyCondition(core.UIA_IsOffscreenPropertyId, False)
    cond = ia.CreateAndCondition(visible, ia.CreateOrCondition(is_pwd, is_edit))
    cache = ia.CreateCacheRequest()
    for prop in (core.UIA_NamePropertyId, core.UIA_AutomationIdPropertyId,
                 core.UIA_IsPasswordPropertyId, core.UIA_BoundingRectanglePropertyId):
        cache.AddProperty(prop)                   # bewusst ohne Value-Eigenschaft: Inhalt tabu

    found = ia.GetRootElement().FindAllBuildCache(core.TreeScope_Descendants, cond, cache)
    rects: List[Rect] = []
    for i in range(found.Length):
        el = found.GetElement(i)
        try:
            sensitive = bool(el.CachedIsPassword) or is_sensitive_name(
                el.CachedName or "", el.CachedAutomationId or "")
            if not sensitive:
                continue
            rc = el.CachedBoundingRectangle
            if rc.right > rc.left and rc.bottom > rc.top:
                rects.append((rc.left, rc.top, rc.right, rc.bottom))
        except Exception:
            log.debug("Element für Schwärzung nicht lesbar", exc_info=True)
    return rects


class RedactionFinder:
    """Beantwortet Suchen nach sensiblen Feldern in einem eigenen UI-Automation-Thread."""

    def __init__(self, finder=None) -> None:
        self._finder = finder                     # austauschbar (Tests): auto_client -> Rects
        self._queue: "queue.Queue[Optional[Future]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._failed = not IS_WINDOWS
        self._busy_since: Optional[float] = None
        self._lock = threading.Lock()
        self._pending: "Optional[Future]" = None     # wartende, noch nicht gestartete Suche

    def submit(self) -> "Future[Optional[List[Rect]]]":
        """Startet die Suche; das Ergebnis ist ``None``, wenn sie nicht möglich war."""
        fut: "Future[Optional[List[Rect]]]" = Future()
        busy = self._busy_since
        if self._failed or (busy is not None and time.monotonic() - busy > STUCK_SECONDS):
            fut.set_result(None)                  # Zielprogramm hängt: nicht auch noch warten
            return fut
        with self._lock:
            if self._pending is not None:
                # Es wartet schon eine noch nicht gestartete Suche; sie beginnt nach diesem
                # Aufruf und ist damit aktuell genug. So teilen sich Klickserien eine Suche.
                return self._pending
            self._pending = fut
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()
            self._queue.put(fut)
        return fut

    @staticmethod
    def result(fut: "Future[Optional[List[Rect]]]", timeout: float = REDACT_TIMEOUT
               ) -> Optional[List[Rect]]:
        try:
            return fut.result(timeout=timeout)
        except Exception:                         # Timeout oder Fehler: ohne Schwärzung
            return None                           # (Future wird ggf. von anderen geteilt)

    def close(self) -> None:
        self._queue.put(None)

    def _loop(self) -> None:
        try:
            import uiautomation as auto
            from uiautomation.uiautomation import _AutomationClient
            init = auto.UIAutomationInitializerInThread()
            client = _AutomationClient.instance()
        except Exception:
            log.warning("UI Automation nicht verfügbar – sensible Felder werden nicht geschwärzt.")
            self._failed = True
            self._drain()
            return
        finder = self._finder or find_sensitive_rects
        with init:
            while True:
                fut = self._queue.get()
                if fut is None:
                    self._drain()
                    return
                with self._lock:
                    if self._pending is fut:
                        self._pending = None      # ab jetzt startet eine neue Suche für neue Aufrufer
                if not fut.set_running_or_notify_cancel():
                    continue
                self._busy_since = time.monotonic()
                try:
                    fut.set_result(finder(client))
                except Exception:
                    log.debug("Suche nach sensiblen Feldern fehlgeschlagen", exc_info=True)
                    fut.set_result(None)
                finally:
                    self._busy_since = None

    def _drain(self) -> None:
        while True:
            try:
                fut = self._queue.get_nowait()
            except queue.Empty:
                return
            if fut is not None and fut.set_running_or_notify_cancel():
                fut.set_result(None)
