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

from .exporter import export_docx
from .recorder import Recorder
from .security import IS_WINDOWS

log = logging.getLogger(__name__)


def list_monitors() -> List[dict]:
    """Einzelne Monitore (ohne den virtuellen Gesamtbildschirm mss.monitors[0])."""
    with mss.mss() as sct:
        return [dict(m) for m in sct.monitors[1:]]


def monitor_label(index: int, m: dict) -> str:
    return f"Monitor {index}: {m['width']}×{m['height']} (Position {m['left']}, {m['top']})"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Process Recorder")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self._monitors = list_monitors()
        self._recorder: Optional[Recorder] = None
        self._workdir: Optional[Path] = None
        self._window_rect = None            # wird bei <Configure> aktualisiert (thread-sicher lesbar)
        self.bind("<Configure>", self._on_configure)

        self._build_ui()
        self._tick()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.grid()

        ttk.Label(frame, text="Zu überwachender Bildschirm:").grid(sticky="w")
        labels = [monitor_label(i, m) for i, m in enumerate(self._monitors, start=1)]
        self._combo = ttk.Combobox(frame, values=labels, state="readonly", width=46)
        self._combo.current(0)
        self._combo.grid(pady=(2, 10), sticky="ew")

        buttons = ttk.Frame(frame)
        buttons.grid(sticky="ew")
        self._start_btn = tk.Button(buttons, text="● Start", width=14, height=2,
                                    bg="#2e9d4f", fg="white", font=("Segoe UI", 11, "bold"),
                                    command=self._start)
        self._stop_btn = tk.Button(buttons, text="■ Stopp", width=14, height=2,
                                   bg="#c62828", fg="white", font=("Segoe UI", 11, "bold"),
                                   command=self._stop, state="disabled")
        self._start_btn.pack(side="left", expand=True, padx=(0, 6))
        self._stop_btn.pack(side="left", expand=True, padx=(6, 0))

        self._status = tk.StringVar(value="Bereit.")
        ttk.Label(frame, textvariable=self._status, wraplength=380).grid(pady=(12, 0), sticky="w")
        hint = ("Tipp: Dieses Fenster auf einen anderen Monitor schieben – Klicks darauf werden "
                "ignoriert, es wäre aber auf Screenshots sichtbar.")
        if not IS_WINDOWS:
            hint += ("\nAchtung: Der Schutz für UAC-/Admin-Fenster und Passwortfelder ist "
                     "nur unter Windows aktiv!")
        ttk.Label(frame, text=hint, foreground="#666", wraplength=380).grid(pady=(8, 0), sticky="w")

    def _on_configure(self, _event=None) -> None:
        self._window_rect = (self.winfo_rootx(), self.winfo_rooty(),
                             self.winfo_width(), self.winfo_height())

    def _tick(self) -> None:
        rec = self._recorder
        if rec is not None:
            if rec.paused:
                self._status.set("⏸ Geschützter Bereich erkannt – Aufnahme pausiert "
                                 f"({rec.step_count} Schritte bisher).")
            else:
                self._status.set(f"● Aufnahme läuft … {rec.step_count} Schritte erfasst.")
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
        self._status.set("Aufnahme wird beendet …")
        self.update_idletasks()
        steps = rec.stop() if rec else []
        label = self._combo.get()

        if not steps:
            messagebox.showinfo("Keine Schritte", "Es wurden keine Schritte aufgezeichnet.")
            self._finish("Bereit.")
            return

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

        self._status.set(f"Word-Dokument wird erstellt ({len(steps)} Schritte) …")
        result: dict = {}

        def work() -> None:
            try:
                export_docx(steps, Path(path), label)
            except Exception as exc:
                log.exception("Export fehlgeschlagen")
                result["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self._wait_export(thread, result, path)

    def _wait_export(self, thread: threading.Thread, result: dict, path: str) -> None:
        if thread.is_alive():
            self.after(200, self._wait_export, thread, result, path)
            return
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
