"""Tkinter-Oberfläche des Process Recorders."""
from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

import mss
from PIL import ImageTk

from .branding import make_logo
from .exporter import export_docx
from .recorder import Recorder
from .security import IS_WINDOWS

log = logging.getLogger(__name__)

BG = "#F4F5FB"
CARD = "#FFFFFF"
TEXT = "#1F2340"
MUTED = "#6B7086"
BORDER = "#E3E5F0"
GREEN, GREEN_H = "#16A34A", "#15803D"
RED, RED_H = "#EF4444", "#DC2626"
IDLE, REC, PAUSE = "#9CA3AF", "#EF4444", "#F59E0B"
FONT = "Segoe UI"


def list_monitors() -> List[dict]:
    """Einzelne Monitore (ohne den virtuellen Gesamtbildschirm mss.monitors[0])."""
    with mss.MSS() as sct:
        return [dict(m) for m in sct.monitors[1:]]


def monitor_label(index: int, m: dict) -> str:
    return f"Monitor {index}: {m['width']}×{m['height']} (Position {m['left']}, {m['top']})"


class RoundButton(tk.Canvas):
    """Flacher Button mit runden Ecken, Hover-Effekt und Deaktiviert-Zustand."""

    def __init__(self, master, text, color, hover, command, width, height, scale) -> None:
        super().__init__(master, width=width, height=height, bg=master["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self._text, self._color, self._hover, self._command = text, color, hover, command
        self._bw, self._bh, self._br = width, height, int(12 * scale)
        self._state = "normal"
        self._over = False
        self.bind("<Enter>", lambda _e: self._set_over(True))
        self.bind("<Leave>", lambda _e: self._set_over(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _set_over(self, value: bool) -> None:
        self._over = value
        self._draw()

    def _click(self, event) -> None:
        if self._state == "normal" and 0 <= event.x <= self._bw and 0 <= event.y <= self._bh:
            self._command()

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._state = kw.pop("state")
            super().configure(cursor="hand2" if self._state == "normal" else "arrow")
            self._draw()
        if cnf or kw:
            return super().configure(cnf, **kw)

    config = configure

    def _draw(self) -> None:
        self.delete("all")
        enabled = self._state == "normal"
        fill = (self._hover if self._over else self._color) if enabled else "#E5E7EB"
        fg = "white" if enabled else "#9CA3AF"
        w, h, r = self._bw, self._bh, self._br
        for x0, y0, x1, y1, start in ((0, 0, 2 * r, 2 * r, 90), (w - 2 * r, 0, w, 2 * r, 0),
                                       (0, h - 2 * r, 2 * r, h, 180), (w - 2 * r, h - 2 * r, w, h, 270)):
            self.create_arc(x0, y0, x1, y1, start=start, extent=90, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        self.create_rectangle(0, r, w, h - r, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=(FONT, 11, "bold"))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Process Recorder")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self._scale = max(1.0, self.winfo_fpixels("1i") / 96)

        self._logo_small = ImageTk.PhotoImage(make_logo(self._px(56)))
        self._icon = ImageTk.PhotoImage(make_logo(64))
        self.iconphoto(True, self._icon)

        self._monitors = list_monitors()
        self._recorder: Optional[Recorder] = None
        self._workdir: Optional[Path] = None
        self._window_rect = None            # wird bei <Configure> aktualisiert (thread-sicher lesbar)
        self.bind("<Configure>", self._on_configure)

        self._build_ui()
        self._tick()

    def _px(self, v: int) -> int:
        return int(v * self._scale)

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        px = self._px
        root = tk.Frame(self, bg=BG)
        root.pack(padx=px(22), pady=px(20))

        # Kopf: Logo + Titel
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x")
        tk.Label(head, image=self._logo_small, bg=BG).pack(side="left")
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", padx=(px(14), 0))
        tk.Label(titles, text="Process Recorder", bg=BG, fg=TEXT,
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(titles, text="Klicks & Eingaben automatisch als Anleitung festhalten",
                 bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        # Karte: Monitor-Auswahl
        card = tk.Frame(root, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=(px(18), 0))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=px(16), pady=px(14))
        tk.Label(inner, text="BILDSCHIRM", bg=CARD, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w")
        labels = [monitor_label(i, m) for i, m in enumerate(self._monitors, start=1)]
        self._combo = ttk.Combobox(inner, values=labels, state="readonly", width=46,
                                   font=(FONT, 10))
        self._combo.current(0)
        self._combo.pack(fill="x", pady=(px(6), 0))

        # Buttons
        bw = px(190)
        buttons = tk.Frame(root, bg=BG)
        buttons.pack(fill="x", pady=(px(16), 0))
        self._start_btn = RoundButton(buttons, "●  Aufnahme starten", GREEN, GREEN_H,
                                      self._start, bw, px(46), self._scale)
        self._stop_btn = RoundButton(buttons, "■  Beenden & speichern", RED, RED_H,
                                     self._stop, bw, px(46), self._scale)
        self._start_btn.pack(side="left")
        self._stop_btn.pack(side="right")
        self._stop_btn.configure(state="disabled")

        # Statuszeile mit farbigem Punkt
        status = tk.Frame(root, bg=BG)
        status.pack(fill="x", pady=(px(16), 0))
        self._dot = tk.Canvas(status, width=px(12), height=px(12), bg=BG,
                              highlightthickness=0, bd=0)
        self._dot_item = self._dot.create_oval(1, 1, px(11), px(11), fill=IDLE, outline=IDLE)
        self._dot.pack(side="left", anchor="n", pady=(px(4), 0))
        self._status = tk.StringVar(value="Bereit.")
        tk.Label(status, textvariable=self._status, bg=BG, fg=TEXT, font=(FONT, 10),
                 wraplength=px(390), justify="left").pack(side="left", padx=(px(8), 0))

        hint = ("Tipp: Dieses Fenster auf einen anderen Monitor schieben – Klicks darauf werden "
                "ignoriert, es wäre aber auf Screenshots sichtbar.")
        if not IS_WINDOWS:
            hint += ("\nAchtung: Der Schutz für UAC-/Admin-Fenster und Passwortfelder ist "
                     "nur unter Windows aktiv!")
        tk.Label(root, text=hint, bg=BG, fg=MUTED, font=(FONT, 9), wraplength=px(390),
                 justify="left").pack(anchor="w", pady=(px(10), 0))
        tk.Label(root, text="made by Lukas Dostal", bg=BG, fg="#A0A4B8",
                 font=(FONT, 8)).pack(anchor="e", pady=(px(10), 0))

    def _on_configure(self, _event=None) -> None:
        self._window_rect = (self.winfo_rootx(), self.winfo_rooty(),
                             self.winfo_width(), self.winfo_height())

    def _tick(self) -> None:
        rec = self._recorder
        color = IDLE
        if rec is not None:
            if rec.paused:
                color = PAUSE
                self._status.set("Geschützter Bereich erkannt – Aufnahme pausiert "
                                 f"({rec.step_count} Schritte bisher).")
            else:
                color = REC
                self._status.set(f"Aufnahme läuft … {rec.step_count} Schritte erfasst.")
        self._dot.itemconfigure(self._dot_item, fill=color, outline=color)
        self.after(300, self._tick)

    # ------------------------------------------------------- Start / Stopp
    def _start(self) -> None:
        if not self._monitors:
            messagebox.showerror("Fehler", "Es wurde kein Bildschirm gefunden.")
            return
        monitor = self._monitors[self._combo.current()]
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
        self._combo.configure(state="disabled")
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")

    def _stop(self) -> None:
        rec, self._recorder = self._recorder, None
        self._stop_btn.configure(state="disabled")
        self._status.set("Aufnahme beendet – bitte Speicherort wählen …")
        self.update_idletasks()
        if rec:
            rec.begin_stop()                     # sofort: Eingaben nicht mehr erfassen
        label = self._combo.get()

        if rec and rec.step_count == 0 and not rec.finish():     # nichts aufgezeichnet
            messagebox.showinfo("Keine Schritte", "Es wurden keine Schritte aufgezeichnet.")
            self._finish("Bereit.")
            return

        # Der Capture-Worker arbeitet ggf. noch Screenshots ab – währenddessen kann schon
        # der Speicherort gewählt werden.
        default = f"Anleitung_{datetime.now():%Y%m%d_%H%M%S}.docx"
        path = filedialog.asksaveasfilename(
            title="Anleitung speichern", defaultextension=".docx", initialfile=default,
            filetypes=[("Word-Dokument", "*.docx")])
        if not path:
            if messagebox.askyesno("Verwerfen?", "Ohne Speichern gehen alle Schritte verloren. "
                                                 "Wirklich verwerfen?"):
                self._finish("Verworfen.")
                return
            path = str(Path.home() / default)

        self._status.set("Word-Dokument wird erstellt …")
        result: dict = {}

        def work() -> None:
            try:
                steps = rec.finish() if rec else []
                result["count"] = len(steps)
                if steps:
                    export_docx(steps, Path(path), label)
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
        if "error" in result:
            messagebox.showerror("Export fehlgeschlagen", str(result["error"]))
            self._finish("Export fehlgeschlagen.")
        elif not result.get("count"):
            messagebox.showinfo("Keine Schritte", "Es wurden keine Schritte aufgezeichnet.")
            self._finish("Bereit.")
        else:
            messagebox.showinfo("Fertig", f"Anleitung gespeichert:\n{path}")
            self._finish(f"Gespeichert: {path}")

    def _finish(self, message: str) -> None:
        self._cleanup()
        self._status.set(message)
        self._combo.configure(state="readonly")
        self._start_btn.configure(state="normal")

    def _cleanup(self) -> None:
        if self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None

    def destroy(self) -> None:
        if self._recorder:
            self._recorder.stop()
            self._recorder = None
        self._cleanup()
        super().destroy()
