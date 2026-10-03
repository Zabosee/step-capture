"""Tkinter-Oberfläche des Process Recorders."""
from __future__ import annotations

import logging
import queue
import shutil
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

import mss
from PIL import ImageTk

from . import __version__
from .branding import make_logo
from .exporter import export_document
from .recorder import HOTKEY_PAUSE, HOTKEY_TOGGLE, Recorder
from .security import IS_WINDOWS

log = logging.getLogger(__name__)

BG, SURFACE, TEXT, MUTED, BORDER = "#F5F6FA", "#FFFFFF", "#1F2340", "#5B6078", "#D5D8E6"
ACCENT, DANGER, PAUSE = "#4F46E5", "#B91C1C", "#B45309"
FONT = "Segoe UI"
OFF = "#E6E8F0"      # Hintergrund deaktivierter Buttons


def apply_theme(root: tk.Tk, px) -> None:
    """Einheitliches ttk-Design (Farben/Schrift/Fokus) für alle Fenster."""
    root.configure(bg=BG)
    root.option_add("*Text.Font", f"{{{FONT}}} 10")   # nicht *Font: überschreibt ttk-Styles
    root.tk.call("font", "configure", "TkDefaultFont", "-family", FONT, "-size", 10)
    for w in ("Text", "Listbox"):
        root.option_add(f"*{w}.relief", "flat")
        root.option_add(f"*{w}.highlightThickness", 1)
        root.option_add(f"*{w}.highlightBackground", BORDER)
        root.option_add(f"*{w}.highlightColor", ACCENT)
    root.option_add("*Listbox.selectBackground", ACCENT)
    root.option_add("*Listbox.selectForeground", "white")
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, font=(FONT, 10), bordercolor=BORDER,
                focuscolor=ACCENT)
    s.configure("Card.TFrame", background=SURFACE)
    s.configure("Muted.TLabel", foreground=MUTED, font=(FONT, 9))
    s.configure("Title.TLabel", font=(FONT, 16, "bold"))
    s.configure("Warn.TLabel", foreground=DANGER, font=(FONT, 9, "bold"))
    s.configure("Card.TLabel", background=SURFACE)
    s.configure("TButton", padding=(px(14), px(8)), relief="flat", background=BORDER,
                borderwidth=2)
    s.map("TButton", background=[("disabled", OFF), ("active", "#C7CBDD")],
          foreground=[("disabled", MUTED)], bordercolor=[("focus", ACCENT), ("disabled", BORDER)])
    for name, bg, active in (("Primary", ACCENT, "#4338CA"), ("Danger", DANGER, "#991B1B")):
        s.configure(f"{name}.TButton", background=bg, foreground="white", font=(FONT, 10, "bold"))
        s.map(f"{name}.TButton", background=[("disabled", OFF), ("active", active)],
              foreground=[("disabled", MUTED), ("!disabled", "white")],
              bordercolor=[("focus", TEXT), ("disabled", BORDER)])
    for name in ("TCheckbutton", "Card.TCheckbutton"):
        s.configure(name, background=SURFACE if name[0] == "C" else BG, indicatorbackground="white")
        s.map(name, indicatorbackground=[("selected", ACCENT)], bordercolor=[("focus", ACCENT)])
    s.configure("TCombobox", fieldbackground="white", background=BORDER, arrowcolor=TEXT)
    s.configure("TEntry", fieldbackground="white")
    s.map("TCombobox", bordercolor=[("focus", ACCENT)], fieldbackground=[("readonly", "white")])
    s.map("TEntry", bordercolor=[("focus", ACCENT)])
    s.configure("TProgressbar", troughcolor=BORDER, background=ACCENT)


def list_monitors() -> List[dict]:
    """Einzelne Monitore (ohne den virtuellen Gesamtbildschirm mss.monitors[0])."""
    with mss.MSS() as sct:
        return [dict(m) for m in sct.monitors[1:]]


def monitor_label(index: int, m: dict) -> str:
    return f"Monitor {index}: {m['width']}×{m['height']} (Position {m['left']}, {m['top']})"


def _remove_stale_workdirs(max_age_hours: float = 24) -> None:
    """Löscht Screenshot-Ordner abgestürzter Läufe, damit keine Bildschirminhalte liegen bleiben."""
    cutoff = time.time() - max_age_hours * 3600
    for d in Path(tempfile.gettempdir()).glob("process_recorder_*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Process Recorder {__version__}")
        self.resizable(True, False)
        self._topmost = tk.BooleanVar(value=True)
        self.attributes("-topmost", True)
        self._scale = max(1.0, self.winfo_fpixels("1i") / 96)

        self._logo_small = ImageTk.PhotoImage(make_logo(self._px(56)))
        self._icon = ImageTk.PhotoImage(make_logo(64))
        self.iconphoto(True, self._icon)

        self._monitors = list_monitors()
        self._recorder: Optional[Recorder] = None
        self._workdir: Optional[Path] = None
        self._started = 0.0
        self._busy = False
        self._last_status = ""
        self._last_color = ""
        self._window_rect = None            # wird bei <Configure> aktualisiert (thread-sicher lesbar)
        self.bind("<Configure>", self._on_configure)

        self._hotkey_queue: "queue.Queue[str]" = queue.Queue()
        self._hotkeys = None
        apply_theme(self, self._px)
        self._build_ui()
        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_hotkeys()
        self._tick()

    def _start_hotkeys(self) -> None:
        """Globale Kürzel Strg+Alt+R (Start/Ende) und Strg+Alt+P (Pause/Fortsetzen).

        Eigene Auswertung statt pynput.GlobalHotKeys: Letztere erkennt Strg+Alt+<Buchstabe>
        unter Windows nicht zuverlässig (Taste kommt ohne Zeichen an, nur mit Tastencode).
        """
        try:
            from pynput import keyboard
            held: set = set()
            codes = {ord(HOTKEY_TOGGLE.upper()): "toggle", ord(HOTKEY_PAUSE.upper()): "pause"}

            def on_press(key) -> None:
                name = getattr(key, "name", None)
                if name:
                    held.add(name)
                    return
                if (codes.get(getattr(key, "vk", None))
                        and held & {"ctrl", "ctrl_l", "ctrl_r"}
                        and held & {"alt", "alt_l", "alt_r", "alt_gr"}):
                    self._hotkey_queue.put(codes[key.vk])

            def on_release(key) -> None:
                held.discard(getattr(key, "name", None))

            self._hotkeys = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._hotkeys.start()
        except Exception:
            log.exception("Globale Tastenkürzel nicht verfügbar")

    def _handle_hotkeys(self) -> None:
        """Läuft im Tk-Thread (die Listener-Threads legen nur Anfragen in die Queue)."""
        while True:
            try:
                action = self._hotkey_queue.get_nowait()
            except queue.Empty:
                return
            if action == "toggle":
                if self._recorder is not None:
                    self._stop()
                elif self._start_btn.instate(["!disabled"]):
                    self._start()
            elif action == "pause" and self._recorder is not None:
                self._toggle_pause()

    def _toggle_pause(self) -> None:
        rec = self._recorder
        if rec is None:
            return
        rec.set_manual_pause(not rec.manual_paused)
        self._pause_btn.configure(text="Fortsetzen" if rec.manual_paused else "Pause")

    def _px(self, v: int) -> int:
        return int(v * self._scale)

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        px = self._px
        root = ttk.Frame(self, padding=px(20))
        root.pack(fill="both", expand=True)

        head = ttk.Frame(root)
        head.pack(fill="x")
        ttk.Label(head, image=self._logo_small).pack(side="left")
        titles = ttk.Frame(head)
        titles.pack(side="left", padx=(px(16), 0))
        ttk.Label(titles, text="Process Recorder", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="Klicks und Eingaben als Anleitung festhalten",
                  style="Muted.TLabel").pack(anchor="w")

        card = ttk.Frame(root, style="Card.TFrame", padding=px(16))
        card.pack(fill="x", pady=(px(20), 0))
        ttk.Label(card, text="Bildschirm", style="Card.TLabel").pack(anchor="w")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(px(8), 0))
        self._combo = ttk.Combobox(row, state="readonly", width=46)
        self._refresh_btn = ttk.Button(row, text="Aktualisieren", command=self._refresh_monitors)
        self._refresh_btn.pack(side="right", padx=(px(8), 0))
        self._combo.pack(side="left", fill="x", expand=True)
        self._fill_monitors()
        self._zoom = tk.BooleanVar(value=True)
        for text, var, cmd in (("Zoom-Ausschnitt um jeden Klick einfügen", self._zoom, None),
                               ("Fenster immer im Vordergrund", self._topmost, self._apply_topmost)):
            ttk.Checkbutton(card, text=text, variable=var, command=cmd,
                            style="Card.TCheckbutton").pack(anchor="w", pady=(px(8), 0))

        buttons = ttk.Frame(root)
        buttons.pack(fill="x", pady=(px(16), 0))
        buttons.columnconfigure((0, 1, 2), weight=1, uniform="btn")
        self._start_btn = ttk.Button(buttons, text="Aufnahme starten", style="Primary.TButton",
                                     command=self._start)
        self._pause_btn = ttk.Button(buttons, text="Pause", command=self._toggle_pause,
                                     state="disabled")
        self._stop_btn = ttk.Button(buttons, text="Aufnahme beenden", style="Danger.TButton",
                                    command=self._stop, state="disabled")
        for col, btn in enumerate((self._start_btn, self._pause_btn, self._stop_btn)):
            btn.grid(row=0, column=col, sticky="ew", padx=px(4))

        self._status_row = ttk.Frame(root)
        self._status_row.pack(fill="x", pady=(px(16), 0))
        self._dot = tk.Canvas(self._status_row, width=px(12), height=px(12), bg=BG,
                              highlightthickness=0)
        self._dot_item = self._dot.create_oval(1, 1, px(11), px(11), fill=MUTED, outline=MUTED)
        self._dot.pack(side="left", anchor="n", pady=(px(4), 0))
        self._status = tk.StringVar(value="Bereit.")
        self._status_label = ttk.Label(self._status_row, textvariable=self._status)
        self._status_label.pack(side="left", padx=(px(8), 0))
        self._progress = ttk.Progressbar(root, mode="indeterminate")

        self._hints = [ttk.Label(
            root, style="Muted.TLabel",
            text=f"Kürzel: Strg+Alt+{HOTKEY_TOGGLE.upper()} Start/Ende, "
                 f"Strg+Alt+{HOTKEY_PAUSE.upper()} Pause\n"
                 "Tipp: Fenster auf einen anderen Monitor schieben, sonst erscheint es auf den "
                 "Screenshots.")]
        if not IS_WINDOWS:
            self._hints.append(ttk.Label(
                root, style="Warn.TLabel", text="Achtung: Der Schutz für UAC-/Admin-Fenster und "
                                                "Passwortfelder ist nur unter Windows aktiv!"))
        for lbl in self._hints:
            lbl.pack(anchor="w", pady=(px(8), 0))
        ttk.Label(root, text=f"Version {__version__}", style="Muted.TLabel").pack(
            anchor="e", pady=(px(8), 0))

    def _apply_topmost(self) -> None:
        self.attributes("-topmost", self._topmost.get())

    def _fill_monitors(self) -> None:
        old = self._combo.current()
        self._combo["values"] = [monitor_label(i, m) for i, m in enumerate(self._monitors, start=1)]
        if self._monitors:
            self._combo.current(old if 0 <= old < len(self._monitors) else 0)

    def _refresh_monitors(self) -> None:
        if self._recorder is None and not self._busy:
            self._monitors = list_monitors()
            self._fill_monitors()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self._progress.pack(fill="x", pady=(self._px(8), 0), after=self._status_row)
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.pack_forget()

    def _on_close(self) -> None:
        if self._recorder is not None or self._busy:
            if not messagebox.askyesno("Beenden?", "Die Aufnahme bzw. der Export läuft noch. "
                                                   "Alle nicht gespeicherten Schritte gehen "
                                                   "verloren. Wirklich beenden?", parent=self):
                return
        self.destroy()

    def _on_configure(self, event=None) -> None:
        if event is not None and event.widget is self and hasattr(self, "_hints"):
            wrap = max(self._px(200), event.width - self._px(80))
            self._status_label.configure(wraplength=wrap)
            for lbl in self._hints:
                lbl.configure(wraplength=wrap)
        self._window_rect = (self.winfo_rootx(), self.winfo_rooty(),
                             self.winfo_width(), self.winfo_height())

    def _tick(self) -> None:
        rec = self._recorder
        color = MUTED
        if rec is not None:
            secs = int(time.monotonic() - self._started)
            clock = f"{secs // 60:02d}:{secs % 60:02d}"
            if rec.manual_paused:
                color = PAUSE
                text = (f"Pausiert ({rec.step_count} Schritte bisher) – "
                        f"Strg+Alt+{HOTKEY_PAUSE.upper()} zum Fortsetzen.")
            elif rec.protected:
                color = PAUSE
                text = ("Geschützter Bereich erkannt – Aufnahme pausiert "
                        f"({rec.step_count} Schritte bisher).")
            else:
                color = DANGER
                text = f"Aufnahme läuft · {clock} · {rec.step_count} Schritte"
                if rec.password_detection_failed:
                    color = PAUSE
                    text = ("ACHTUNG: Passwortfelder in Browsern werden nicht erkannt "
                            "(UI Automation fehlt) – keine Passwörter eingeben! · " + text)
            if text != self._last_status:
                self._last_status = text
                self._status.set(text)
        if color != self._last_color:
            self._last_color = color
            self._dot.itemconfigure(self._dot_item, fill=color, outline=color)
        self._handle_hotkeys()
        self.after(150, self._tick)

    # ------------------------------------------------------- Start / Stopp
    def _start(self) -> None:
        if not self._monitors:
            messagebox.showerror("Fehler", "Es wurde kein Bildschirm gefunden.")
            return
        monitor = self._monitors[self._combo.current()]
        _remove_stale_workdirs()
        self._workdir = Path(tempfile.mkdtemp(prefix="process_recorder_"))
        try:
            self._recorder = Recorder(monitor, self._workdir, lambda: self._window_rect)
            self._recorder.start()
        except Exception as exc:
            log.exception("Start fehlgeschlagen")
            self._recorder = None
            self._cleanup()
            messagebox.showerror("Fehler", f"Aufnahme konnte nicht gestartet werden:\n{exc}")
            return
        self._started = time.monotonic()
        self._combo.configure(state="disabled")
        self._refresh_btn.configure(state="disabled")
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._pause_btn.configure(text="Pause")
        self._pause_btn.configure(state="normal")

    def _stop(self) -> None:
        rec, self._recorder = self._recorder, None
        self._stop_btn.configure(state="disabled")
        self._pause_btn.configure(state="disabled")
        self._status.set("Vorschau wird vorbereitet …")
        self._set_busy(True)
        self.update_idletasks()
        if rec:
            rec.begin_stop()                     # sofort: Eingaben nicht mehr erfassen
        label = self._combo.get()
        result: dict = {}

        def collect() -> None:                   # wartet auf noch offene Screenshots
            result["steps"] = rec.finish() if rec else []

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()
        self._wait_collect(thread, result, label)

    def _wait_collect(self, thread: threading.Thread, result: dict, label: str) -> None:
        if thread.is_alive():
            self.after(50, self._wait_collect, thread, result, label)
            return
        self._set_busy(False)
        steps = result.get("steps") or []
        if not steps:
            messagebox.showinfo("Keine Schritte", "Es wurden keine Schritte aufgezeichnet.")
            self._finish("Bereit.")
            return
        self._review(steps, label)

    def _review(self, steps: list, label: str) -> None:
        from .editor import StepEditor

        editor = StepEditor(self, steps, self._scale)
        self.wait_window(editor)
        if editor.result is None:
            self._finish("Aufnahme verworfen.")
            return
        steps, title, intro, outro = editor.result

        default = f"Anleitung_{datetime.now():%Y%m%d_%H%M%S}.docx"
        path = filedialog.asksaveasfilename(
            title="Anleitung speichern", defaultextension=".docx", initialfile=default,
            filetypes=[("Word-Dokument", "*.docx"), ("PDF-Dokument", "*.pdf")])
        if not path:
            if messagebox.askyesno("Verwerfen?", "Ohne Speichern gehen alle Schritte verloren. "
                                                 "Wirklich verwerfen?"):
                self._finish("Aufnahme verworfen.")
                return
            path = str(Path.home() / default)

        self._status.set("Dokument wird erstellt …")
        self._set_busy(True)
        result: dict = {}
        zoom = self._zoom.get()

        def work() -> None:
            try:
                export_document(steps, Path(path), label, title=title, intro=intro,
                                outro=outro, zoom=zoom)
            except Exception as exc:
                log.exception("Export fehlgeschlagen")
                result["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self._wait_export(thread, result, path)

    def _wait_export(self, thread: threading.Thread, result: dict, path: str) -> None:
        if thread.is_alive():
            self.after(100, self._wait_export, thread, result, path)
            return
        self._set_busy(False)
        if "error" in result:
            messagebox.showerror("Export fehlgeschlagen", str(result["error"]))
            self._finish("Export fehlgeschlagen.")
        else:
            messagebox.showinfo("Fertig", f"Anleitung gespeichert:\n{path}")
            self._finish(f"Gespeichert: {path}")

    def _finish(self, message: str) -> None:
        self._cleanup()
        self._status.set(message)
        self._combo.configure(state="readonly")
        self._refresh_btn.configure(state="normal")
        self._start_btn.configure(state="normal")

    def _cleanup(self) -> None:
        if self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None

    def destroy(self) -> None:
        if self._hotkeys:
            self._hotkeys.stop()
        if self._recorder:
            self._recorder.stop()
            self._recorder = None
        self._cleanup()
        super().destroy()
