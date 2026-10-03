"""Aufnahme-Logik: Maus-/Tastatur-Listener, Screenshots, Sicherheits-Filter."""
from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .models import Step, app_of, element_kind, element_name
from .security import SensitiveContextDetector
from .target import TargetResolver

log = logging.getLogger(__name__)

GRACE_SECONDS = 0.6          # so viel Text vor Erkennung eines sensiblen Kontexts wird verworfen
POLL_INTERVAL = 0.15         # Takt der Sicherheitsüberwachung
TEXT_FIELDS = ("Eingabefeld", "Zahlenfeld", "Auswahlfeld")  # Klick hinein + Tippen = 1 Schritt
TARGET_TIMEOUT = 1.0         # so lange wartet ein Schritt maximal auf das Klickziel
DOUBLE_CLICK_SECONDS = 0.4
DOUBLE_CLICK_DISTANCE = 6

Rect = Tuple[int, int, int, int]  # x, y, Breite, Höhe

# Globale Tastenkürzel der App (Strg+Alt+<Buchstabe>) – werden nie aufgezeichnet
HOTKEY_TOGGLE = "r"          # Aufnahme starten / beenden
HOTKEY_PAUSE = "p"           # Aufnahme pausieren / fortsetzen

_SPECIAL_KEYS = {"enter": "Enter", "esc": "Esc", "delete": "Entf", "tab": "Tab",
                 "home": "Pos1", "end": "Ende", "page_up": "Bild auf", "page_down": "Bild ab",
                 "insert": "Einfg", "print_screen": "Druck"}


@dataclass
class _Event:
    kind: str                    # "click" | "text" | "key" | "protected"
    ts: float
    x: int = 0
    y: int = 0
    button: str = "left"
    text: str = ""
    capture: bool = True         # False: kein Screenshot (sensibler Kontext)
    target: Optional[Future] = None   # Klickziel (UI Automation), wird im Hintergrund ermittelt


class Recorder:
    """Zeichnet Klicks und Texteingaben eines Monitors als Liste von :class:`Step` auf."""

    def __init__(self, monitor: dict, workdir: Path,
                 ignore_rect: Optional[Callable[[], Optional[Rect]]] = None) -> None:
        self._monitor = dict(monitor)
        self._workdir = Path(workdir)
        self._ignore_rect = ignore_rect          # z. B. Fenster des Recorders selbst

        self.steps: List[Step] = []              # wird nur vom Worker-Thread beschrieben
        self._last_app = ""                       # Programm des letzten Klicks

        self._queue: "queue.Queue[Optional[_Event]]" = queue.Queue()
        self._lock = threading.Lock()
        self._buffer: List[Tuple[float, str]] = []   # (Zeitstempel, Zeichen)
        self._modifiers: set = set()
        self._sensitive = False
        self._manual_pause = False
        self._stop = threading.Event()
        self._poke = threading.Event()
        self._detector = SensitiveContextDetector()
        self._resolver = TargetResolver()
        self._threads: List[threading.Thread] = []
        self._listeners: list = []
        self._running = False

    # ------------------------------------------------------------------ Status
    @property
    def protected(self) -> bool:
        """True, solange ein geschützter Bereich (UAC/Passwort) aktiv ist."""
        return self._sensitive

    @property
    def manual_paused(self) -> bool:
        return self._manual_pause

    def set_manual_pause(self, value: bool) -> None:
        """Pausiert/fortsetzt die Aufnahme auf Wunsch des Nutzers."""
        if value == self._manual_pause:
            return
        if value:
            self._flush_text()                   # bisher getippter Text bleibt erhalten
        self._manual_pause = value
        log.info("Aufnahme %s (manuell)", "pausiert" if value else "fortgesetzt")

    @property
    def password_detection_failed(self) -> bool:
        """True, wenn UI Automation fehlt: Passwortfelder in Browsern/WPF werden dann nicht erkannt."""
        return self._detector._uia_failed

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

    def begin_stop(self) -> None:
        """Beendet die Eingabe-Erfassung sofort; Restarbeit läuft im Hintergrund weiter."""
        if not self._running:
            return
        self._running = False
        for listener in self._listeners:
            listener.stop()
        self._flush_text()
        self._stop.set()
        self._poke.set()
        self._queue.put(None)                    # beendet den Capture-Worker nach Restarbeit

    def finish(self) -> List[Step]:
        """Wartet auf den Capture-Worker und liefert alle Schritte in zeitlicher Reihenfolge."""
        for t in self._threads:
            t.join(timeout=30)
        # Erst jetzt schließen: der Worker braucht beide Dienste, bis die Warteschlange leer ist
        self._resolver.close()
        return list(self.steps)

    def stop(self) -> List[Step]:
        """Beendet die Aufnahme und liefert alle Schritte (blockierend)."""
        self.begin_stop()
        return self.finish()

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
            log.info("Geschützter Bereich erkannt – Aufnahme pausiert (Grund: %s)",
                     self._detector.reason)
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
        while not self._stop.is_set():
            try:
                self._set_sensitive(self._detector.is_sensitive())
            except Exception:
                log.exception("Sicherheitsüberwachung fehlgeschlagen")
                self._set_sensitive(True)        # fail-safe
            self._poke.wait(POLL_INTERVAL)
            self._poke.clear()

    # -------------------------------------------------------------- Tastatur
    _MODIFIER_NAMES = {"ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr",
                       "cmd", "cmd_l", "cmd_r", "shift", "shift_l", "shift_r"}

    def _held(self, *names: str) -> bool:
        return any(n in self._modifiers for n in names)

    def _ctrl(self) -> bool:
        """Strg gedrückt (AltGr meldet Windows als Strg+Alt und zählt nicht)."""
        return self._held("ctrl", "ctrl_l", "ctrl_r") and not self._held("alt_gr")

    @staticmethod
    def _key_label(key) -> Optional[str]:
        """Lesbarer Name der gedrückten (Nicht-Modifikator-)Taste, z. B. „S“, „F5“, „Enter“."""
        name = getattr(key, "name", None)
        if name:
            if name in _SPECIAL_KEYS:
                return _SPECIAL_KEYS[name]
            if name.startswith("f") and name[1:].isdigit():
                return name.upper()
            return None
        vk = getattr(key, "vk", None)
        if vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
            return chr(vk)                       # Strg+<Buchstabe> liefert sonst Steuerzeichen
        char = getattr(key, "char", None)
        return char.upper() if char and char.isprintable() else None

    def _combo_label(self, key_label: str) -> str:
        mods = []
        if self._ctrl():
            mods.append("Strg")
        if self._held("alt", "alt_l"):
            mods.append("Alt")
        if self._held("shift", "shift_l", "shift_r"):
            mods.append("Umschalt")
        if self._held("cmd", "cmd_l", "cmd_r"):
            mods.append("Win")
        return "+".join(mods + [key_label])

    def _is_app_hotkey(self, key) -> bool:
        """Strg+Alt+R / Strg+Alt+P gehören der App und werden nicht mitgeschnitten."""
        if not (self._held("ctrl", "ctrl_l", "ctrl_r") and self._held("alt", "alt_l", "alt_gr")):
            return False
        label = self._key_label(key)
        return bool(label) and label.lower() in (HOTKEY_TOGGLE, HOTKEY_PAUSE)

    def _on_key_press(self, key) -> None:
        try:
            name = getattr(key, "name", None)
            if name in self._MODIFIER_NAMES:
                self._modifiers.add(name)
                return
            if self._is_app_hotkey(key):
                return
            if self._manual_pause:
                return
            # Synchrone Schnellprüfung, damit zwischen zwei Poll-Takten nichts durchrutscht
            if not self._sensitive and self._detector.is_sensitive_fast():
                self._set_sensitive(True)
            if self._sensitive:
                return

            label = self._key_label(key)
            ctrl = self._ctrl()
            alt = self._held("alt", "alt_l")
            win = self._held("cmd", "cmd_l", "cmd_r")

            if (ctrl or alt or win) and label:
                self._flush_text()               # Kürzel beendet die laufende Texteingabe
                self._queue.put(_Event("key", time.time(), text=self._combo_label(label)))
            elif name == "tab":
                self._flush_text()
            elif name in ("enter", "esc", "delete") or (name and name[0] == "f" and name[1:].isdigit()):
                self._flush_text()
                self._queue.put(_Event("key", time.time(), text=label))
            elif name == "backspace":
                with self._lock:
                    if self._buffer:
                        self._buffer.pop()
            elif name == "space":
                self._append(" ")
            else:
                char = getattr(key, "char", None)
                if char and char.isprintable() and not ctrl:     # AltGr (@, €) ist Text
                    self._append(char)
        except Exception:
            log.exception("Fehler im Tastatur-Callback")

    def _on_key_release(self, key) -> None:
        self._modifiers.discard(getattr(key, "name", None))

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
            if self._sensitive or self._manual_pause:
                return
            m = self._monitor
            if not (m["left"] <= x < m["left"] + m["width"]
                    and m["top"] <= y < m["top"] + m["height"]):
                return                            # anderer Monitor
            self._flush_text()                    # Text endet mit dem Klick
            self._queue.put(_Event("click", time.time(), x=int(x), y=int(y),
                                   button=getattr(button, "name", "left"),
                                   target=self._resolver.submit(int(x), int(y))))
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

        with mss.MSS() as sct:
            while True:
                event = self._queue.get()
                if event is None:
                    break
                try:
                    self._handle_event(sct, event)
                except Exception:
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
            if (last and last.kind in ("click", "text") and last.click_rel
                    and last.button == ev.button
                    and ev.ts - last.timestamp <= DOUBLE_CLICK_SECONDS
                    and abs(last.click_rel[0] - rel[0]) <= DOUBLE_CLICK_DISTANCE
                    and abs(last.click_rel[1] - rel[1]) <= DOUBLE_CLICK_DISTANCE):
                last.clicks += 1                  # Doppelklick statt zweitem Schritt
                last.timestamp = ev.ts
                return
            path = self._grab(sct)
            target = self._target_text(ev)
            if self._open_text(last):             # „Text eingeben und auf … klicken“
                last.timestamp, last.image_path, last.click_rel = ev.ts, path, rel
                last.button, last.target = ev.button, target
                return
            if (self._plain_click(last, "Auswahlfeld") and not last.field
                    and ev.button == "left" and element_name(target)
                    and element_kind(target) in ("Listeneintrag", "Menüeintrag")):
                # „Wählen Sie im Auswahlfeld „Land“ den Eintrag „Deutschland“ aus.“
                last.field, last.target = last.target, target
                last.timestamp, last.image_path, last.click_rel = ev.ts, path, rel
                return
            step = Step("click", ev.ts, image_path=path, click_rel=rel, button=ev.button,
                        target=target)
            app = app_of(target)
            if app and app != self._last_app and "Taskleiste" not in (target or ""):
                step.switch_to = app              # „Wechseln Sie zu „Word“. …“
                self._last_app = app
            self.steps.append(step)
        elif ev.kind == "key":
            path = self._grab(sct)
            last = self.steps[-1] if self.steps else None
            if self._open_text(last):             # „Text eingeben und Enter drücken“
                last.timestamp, last.image_path, last.key = ev.ts, path, ev.text
                return
            self.steps.append(Step("key", ev.ts, image_path=path, text=ev.text))
        elif ev.kind == "text":
            path = self._grab(sct) if ev.capture else None
            last = self.steps[-1] if self.steps else None
            if any(self._plain_click(last, kind) for kind in TEXT_FIELDS) \
                    and element_name(last.target):
                # Klick ins Feld + Tippen: „Geben Sie in das Eingabefeld „Name“ … ein.“
                last.kind, last.text, last.timestamp = "text", ev.text, ev.ts
                last.field, last.target, last.click_rel = last.target, None, None
                if path:
                    last.image_path = path
                return
            self.steps.append(Step("text", ev.ts, image_path=path, text=ev.text))

    @staticmethod
    def _plain_click(step: Optional[Step], kind: str) -> bool:
        """Einfacher Linksklick auf ein Element des Typs ``kind``."""
        return bool(step and step.kind == "click" and step.button == "left"
                    and step.clicks == 1 and element_kind(step.target) == kind)

    @staticmethod
    def _open_text(step: Optional[Step]) -> bool:
        """Texteingabe, die noch mit keinem Klick/keiner Taste abgeschlossen wurde."""
        return bool(step and step.kind == "text" and not step.click_rel and not step.key)

    @staticmethod
    def _target_text(ev: _Event) -> Optional[str]:
        if ev.target is None:
            return None
        try:
            return ev.target.result(timeout=TARGET_TIMEOUT)
        except Exception:                         # Timeout oder Fehler: Schritt ohne Ziel
            return None

    def _grab(self, sct) -> Path:
        from PIL import Image

        shot = sct.grab(self._monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        path = self._workdir / f"step_{len(self.steps):04d}.jpg"
        img.save(path, quality=88)
        return path
