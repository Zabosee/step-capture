"""Aufnahme-Logik: Maus-/Tastatur-Listener, Screenshots, Sicherheits-Filter."""
from __future__ import annotations

import contextlib
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .models import Step
from .security import SensitiveContextDetector

log = logging.getLogger(__name__)

GRACE_SECONDS = 0.6          # so viel Text vor Erkennung eines sensiblen Kontexts wird verworfen
POLL_INTERVAL = 0.15         # Takt der Sicherheitsüberwachung
DOUBLE_CLICK_SECONDS = 0.4
DOUBLE_CLICK_DISTANCE = 6

Rect = Tuple[int, int, int, int]  # x, y, Breite, Höhe


@dataclass
class _Event:
    kind: str                    # "click" | "text" | "protected"
    ts: float
    x: int = 0
    y: int = 0
    button: str = "left"
    text: str = ""
    capture: bool = True         # False: kein Screenshot (sensibler Kontext)


class Recorder:
    """Zeichnet Klicks und Texteingaben eines Monitors als Liste von :class:`Step` auf."""

    def __init__(self, monitor: dict, workdir: Path,
                 ignore_rect: Optional[Callable[[], Optional[Rect]]] = None) -> None:
        self._monitor = dict(monitor)
        self._workdir = Path(workdir)
        self._ignore_rect = ignore_rect          # z. B. Fenster des Recorders selbst

        self.steps: List[Step] = []              # wird nur vom Worker-Thread beschrieben
        self.error_count = 0

        self._queue: "queue.Queue[Optional[_Event]]" = queue.Queue()
        self._lock = threading.Lock()
        self._buffer: List[Tuple[float, str]] = []   # (Zeitstempel, Zeichen)
        self._modifiers: set = set()
        self._sensitive = False
        self._stop = threading.Event()
        self._poke = threading.Event()
        self._detector = SensitiveContextDetector()
        self._threads: List[threading.Thread] = []
        self._listeners: list = []
        self._running = False

    # ------------------------------------------------------------------ Status
    @property
    def paused(self) -> bool:
        """True, solange ein geschützter Bereich aktiv ist."""
        return self._sensitive

    @property
    def step_count(self) -> int:
        return len(self.steps)

    # ---------------------------------------------------------- Start / Stopp
    def start(self) -> None:
        from pynput import keyboard, mouse  # lazy: benötigt ein Display

        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._workdir.mkdir(parents=True, exist_ok=True)

        for target in (self._capture_worker, self._security_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

        self._listeners = [
            mouse.Listener(on_click=self._on_click),
            keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release),
        ]
        for listener in self._listeners:
            listener.start()

    def stop(self) -> List[Step]:
        """Beendet die Aufnahme und liefert alle Schritte in zeitlicher Reihenfolge."""
        if not self._running:
            return list(self.steps)
        self._running = False
        for listener in self._listeners:
            listener.stop()
        self._flush_text()
        self._stop.set()
        self._poke.set()
        self._queue.put(None)                    # beendet den Capture-Worker nach Restarbeit
        for t in self._threads:
            t.join(timeout=30)
        return list(self.steps)

    # ------------------------------------------------------- Sensibler Kontext
    def _set_sensitive(self, value: bool) -> None:
        """Wechselt den Schutzzustand; beim Eintritt wird ungesicherter Text verworfen."""
        with self._lock:
            if value == self._sensitive:
                return
            self._sensitive = value
            if not value:
                log.info("Geschützter Bereich verlassen – Aufnahme läuft weiter")
                return
            log.info("Geschützter Bereich erkannt – Aufnahme pausiert")
            # Zeichen, die kurz vor der Erkennung getippt wurden, könnten schon
            # zum Passwort gehören -> verwerfen. Älterer Text bleibt erhalten.
            cutoff = time.time() - GRACE_SECONDS
            text = "".join(c for ts, c in self._buffer if ts < cutoff)
            self._buffer.clear()
        now = time.time()
        if text.strip():
            self._queue.put(_Event("text", now, text=text, capture=False))
        self._queue.put(_Event("protected", now, capture=False))

    def _security_loop(self) -> None:
        """Pollt regelmäßig (inkl. UI Automation) auf Admin-Fenster / Passwortfelder."""
        try:
            import uiautomation as auto
            init = auto.UIAutomationInitializerInThread()
        except Exception:
            init = contextlib.nullcontext()
        with init:
            while not self._stop.is_set():
                try:
                    self._set_sensitive(self._detector.is_sensitive())
                except Exception:
                    log.exception("Sicherheitsüberwachung fehlgeschlagen")
                    self._set_sensitive(True)    # fail-safe
                self._poke.wait(POLL_INTERVAL)
                self._poke.clear()

    # -------------------------------------------------------------- Tastatur
    def _on_key_press(self, key) -> None:
        from pynput.keyboard import Key

        try:
            if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r, Key.alt_gr, Key.cmd,
                       getattr(Key, "cmd_l", None), getattr(Key, "cmd_r", None)):
                self._modifiers.add(key)
                return
            # Synchrone Schnellprüfung, damit zwischen zwei Poll-Takten nichts durchrutscht
            if not self._sensitive and self._detector.is_sensitive_fast():
                self._set_sensitive(True)
            if self._sensitive:
                return

            if key in (Key.tab, Key.enter):
                self._flush_text()
            elif key == Key.backspace:
                with self._lock:
                    if self._buffer:
                        self._buffer.pop()
            elif key == Key.space:
                self._append(" ")
            else:
                char = getattr(key, "char", None)
                # Tastenkombinationen (Strg+C usw.) sind keine Texteingabe; AltGr (@, €) schon
                shortcut = any(m in self._modifiers for m in
                               (Key.ctrl, Key.ctrl_l, Key.ctrl_r)) and Key.alt_gr not in self._modifiers
                if char and char.isprintable() and not shortcut:
                    self._append(char)
        except Exception:
            log.exception("Fehler im Tastatur-Callback")

    def _on_key_release(self, key) -> None:
        self._modifiers.discard(key)

    def _append(self, char: str) -> None:
        with self._lock:
            self._buffer.append((time.time(), char))

    def _flush_text(self) -> None:
        """Schließt den aktuellen Textpuffer als Schritt ab."""
        with self._lock:
            text = "".join(c for _, c in self._buffer)
            self._buffer.clear()
            if self._sensitive:
                return
        if text.strip():
            self._queue.put(_Event("text", time.time(), text=text))

    # ------------------------------------------------------------------ Maus
    def _on_click(self, x, y, button, pressed) -> None:
        if not pressed:
            return
        try:
            if self._in_rect(x, y, self._ignore_rect() if self._ignore_rect else None):
                return                            # Klick auf das Recorder-Fenster
            if not self._sensitive and self._detector.is_sensitive_fast():
                self._set_sensitive(True)
            self._poke.set()
            if self._sensitive:
                return
            m = self._monitor
            if not (m["left"] <= x < m["left"] + m["width"]
                    and m["top"] <= y < m["top"] + m["height"]):
                return                            # anderer Monitor
            self._flush_text()                    # Text endet mit dem Klick
            self._queue.put(_Event("click", time.time(), x=int(x), y=int(y),
                                   button=getattr(button, "name", "left")))
        except Exception:
            log.exception("Fehler im Maus-Callback")

    @staticmethod
    def _in_rect(x, y, rect: Optional[Rect]) -> bool:
        if not rect:
            return False
        rx, ry, rw, rh = rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    # ---------------------------------------------------------- Capture-Thread
    def _capture_worker(self) -> None:
        """Erstellt Screenshots und Schritte (mss-Instanzen sind thread-gebunden)."""
        import mss

        with mss.mss() as sct:
            while True:
                event = self._queue.get()
                if event is None:
                    break
                try:
                    self._handle_event(sct, event)
                except Exception:
                    self.error_count += 1
                    log.exception("Schritt konnte nicht aufgezeichnet werden")

    def _handle_event(self, sct, ev: _Event) -> None:
        if ev.kind == "protected":
            # Aufeinanderfolgende Platzhalter zusammenfassen
            if not (self.steps and self.steps[-1].kind == "protected"):
                self.steps.append(Step("protected", ev.ts))
            return

        if ev.kind == "click":
            last = self.steps[-1] if self.steps else None
            rel = (ev.x - self._monitor["left"], ev.y - self._monitor["top"])
            if (last and last.kind == "click" and last.button == ev.button
                    and ev.ts - last.timestamp <= DOUBLE_CLICK_SECONDS
                    and abs(last.click_rel[0] - rel[0]) <= DOUBLE_CLICK_DISTANCE
                    and abs(last.click_rel[1] - rel[1]) <= DOUBLE_CLICK_DISTANCE):
                last.clicks += 1                  # Doppelklick statt zweitem Schritt
                last.timestamp = ev.ts
                return
            path = self._grab(sct)
            self.steps.append(Step("click", ev.ts, image_path=path, click_rel=rel,
                                   button=ev.button))
        elif ev.kind == "text":
            path = self._grab(sct) if ev.capture else None
            self.steps.append(Step("text", ev.ts, image_path=path, text=ev.text))

    def _grab(self, sct) -> Path:
        from PIL import Image

        shot = sct.grab(self._monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        path = self._workdir / f"step_{len(self.steps):04d}.jpg"
        img.save(path, quality=88)
        return path
