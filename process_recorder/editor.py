"""Vorschau-Editor: Schritte prüfen, löschen, umsortieren und Beschreibungen anpassen."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageTk

from .exporter import mark_click
from .models import Step

ACCENT = "#6366F1"


class StepEditor(tk.Toplevel):
    """Modaler Dialog. Ergebnis in ``result``: (Schritte, Titel, Einleitung) oder None (verworfen)."""

    def __init__(self, master, steps: List[Step], scale: float) -> None:
        # Farben/Buttons aus gui.py; Import erst hier, damit gui.py diesen Editor importieren kann
        from . import gui
        self._g = gui
        super().__init__(master, bg=gui.BG)
        self.title("Anleitung prüfen und anpassen")
        self.attributes("-topmost", True)
        self._scale = scale
        self.steps = list(steps)
        self.result: Optional[Tuple[List[Step], str, str]] = None
        self._current: Optional[int] = None
        self._photos: Dict[Path, ImageTk.PhotoImage] = {}
        self._build()
        self._refresh(select=0)

        self.protocol("WM_DELETE_WINDOW", self._discard)
        self.bind("<Delete>", lambda _e: self._delete() if self.focus_get() is self._list else None)
        self.transient(master)
        self.grab_set()
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = max(0, master.winfo_rooty() + (master.winfo_height() - h) // 2 - self._px(80))
        self.geometry(f"+{max(0, x)}+{y}")
        self.focus_set()

    def _px(self, v: int) -> int:
        return int(v * self._scale)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        g, px = self._g, self._px
        root = tk.Frame(self, bg=g.BG)
        root.pack(padx=px(18), pady=px(16))

        # Titel + Einleitung
        top = tk.Frame(root, bg=g.BG)
        top.pack(fill="x")
        tk.Label(top, text="TITEL DER ANLEITUNG", bg=g.BG, fg=g.MUTED,
                 font=(g.FONT, 8, "bold")).pack(anchor="w")
        self._title = tk.Entry(top, font=(g.FONT, 11), relief="flat", highlightthickness=1,
                               highlightbackground=g.BORDER, highlightcolor=ACCENT)
        self._title.insert(0, "Prozessdokumentation")
        self._title.pack(fill="x", ipady=px(5), pady=(px(4), px(8)))
        tk.Label(top, text="EINLEITUNG (OPTIONAL)", bg=g.BG, fg=g.MUTED,
                 font=(g.FONT, 8, "bold")).pack(anchor="w")
        self._intro = self._text_box(top, 2)
        self._intro.pack(fill="x", pady=(px(4), 0))

        body = tk.Frame(root, bg=g.BG)
        body.pack(fill="both", pady=(px(14), 0))

        # Links: Schrittliste
        left = tk.Frame(body, bg=g.CARD, highlightthickness=1, highlightbackground=g.BORDER)
        left.pack(side="left", fill="y")
        self._count = tk.Label(left, bg=g.CARD, fg=g.MUTED, font=(g.FONT, 9), anchor="w")
        self._count.pack(fill="x", padx=px(10), pady=(px(8), px(4)))
        list_frame = tk.Frame(left, bg=g.CARD)
        list_frame.pack(fill="both", expand=True, padx=(px(4), 0), pady=(0, px(4)))
        scroll = tk.Scrollbar(list_frame)
        self._list = tk.Listbox(list_frame, width=44, height=17, font=(g.FONT, 10), bd=0,
                                highlightthickness=0, activestyle="none", exportselection=False,
                                selectbackground=ACCENT, selectforeground="white",
                                yscrollcommand=scroll.set, bg=g.CARD, fg=g.TEXT)
        scroll.config(command=self._list.yview)
        self._list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._list.bind("<<ListboxSelect>>", self._on_select)

        # Rechts: Vorschau + Bearbeitung
        right = tk.Frame(body, bg=g.BG)
        right.pack(side="left", fill="both", padx=(px(14), 0))
        self._img_w, self._img_h = px(520), px(300)
        img_frame = tk.Frame(right, bg="#E9EAF3", width=self._img_w, height=self._img_h)
        img_frame.pack()
        img_frame.pack_propagate(False)
        self._img_label = tk.Label(img_frame, bg="#E9EAF3", fg=g.MUTED, font=(g.FONT, 10))
        self._img_label.pack(expand=True)

        tk.Label(right, text="BESCHREIBUNG", bg=g.BG, fg=g.MUTED,
                 font=(g.FONT, 8, "bold")).pack(anchor="w", pady=(px(10), 0))
        self._desc = self._text_box(right, 3)
        self._desc.pack(fill="x", pady=(px(4), 0))
        self._txt_caption = tk.Label(right, text="EINGEGEBENER TEXT", bg=g.BG, fg=g.MUTED,
                                     font=(g.FONT, 8, "bold"))
        self._txt = self._text_box(right, 2)

        # Aktionsleiste
        bar = tk.Frame(root, bg=g.BG)
        bar.pack(fill="x", pady=(px(14), 0))
        small = px(96)
        grey, grey_h = "#6B7086", "#4B5066"
        g.RoundButton(bar, "▲  Hoch", grey, grey_h, lambda: self._move(-1), small, px(38),
                      self._scale).pack(side="left")
        g.RoundButton(bar, "▼  Runter", grey, grey_h, lambda: self._move(1), small, px(38),
                      self._scale).pack(side="left", padx=px(8))
        g.RoundButton(bar, "Schritt löschen", g.RED, g.RED_H, self._delete, px(140), px(38),
                      self._scale).pack(side="left")
        g.RoundButton(bar, "Speichern (Word/PDF) …", g.GREEN, g.GREEN_H, self._save, px(200),
                      px(38), self._scale).pack(side="right")
        g.RoundButton(bar, "Verwerfen", grey, grey_h, self._discard, px(110), px(38),
                      self._scale).pack(side="right", padx=(0, px(8)))

    def _text_box(self, master, height: int) -> tk.Text:
        g = self._g
        return tk.Text(master, height=height, width=60, wrap="word", font=(g.FONT, 10),
                       relief="flat", highlightthickness=1, highlightbackground=g.BORDER,
                       highlightcolor=ACCENT, padx=8, pady=6, undo=True)

    # ----------------------------------------------------------- Liste/Anzeige
    @staticmethod
    def _label(index: int, step: Step) -> str:
        text = " ".join(step.text_for_export().split())
        if step.kind == "protected":
            text = "Geschützter Bereich (nicht aufgezeichnet)"
        return f"{index + 1:>3}   {text if len(text) <= 46 else text[:45] + '…'}"

    def _refresh(self, select: Optional[int] = None) -> None:
        self._list.delete(0, "end")
        for i, step in enumerate(self.steps):
            self._list.insert("end", self._label(i, step))
        self._count.configure(text=f"{len(self.steps)} Schritte")
        self._current = None
        if self.steps and select is not None:
            select = max(0, min(select, len(self.steps) - 1))
            self._list.selection_set(select)
            self._list.see(select)
            self._show(select)
        else:
            self._show(None)

    def _on_select(self, _event=None) -> None:
        sel = self._list.curselection()
        if not sel or sel[0] == self._current:
            return
        self._commit()
        self._show(sel[0])

    def _show(self, index: Optional[int]) -> None:
        self._current = index
        self._desc.delete("1.0", "end")
        self._txt.delete("1.0", "end")
        if index is None:
            self._img_label.configure(image="", text="Keine Schritte")
            self._txt_caption.pack_forget()
            self._txt.pack_forget()
            return
        step = self.steps[index]
        self._desc.insert("1.0", step.text_for_export())
        if step.kind == "text":
            self._txt_caption.pack(anchor="w", pady=(self._px(8), 0))
            self._txt.pack(fill="x", pady=(self._px(4), 0))
            self._txt.insert("1.0", step.text)
        else:
            self._txt_caption.pack_forget()
            self._txt.pack_forget()
        photo = self._photo(step)
        if photo:
            self._img_label.configure(image=photo, text="")
        else:
            self._img_label.configure(image="", text="Kein Screenshot (geschützter Bereich)"
                                      if step.kind == "protected" else "Kein Screenshot")

    def _photo(self, step: Step) -> Optional[ImageTk.PhotoImage]:
        path = step.image_path
        if not path or not Path(path).exists():
            return None
        if path not in self._photos:
            with Image.open(path) as raw:
                img = raw.convert("RGB")
            if step.click_rel:
                img = mark_click(img, step.click_rel)
            img.thumbnail((self._img_w, self._img_h), Image.LANCZOS)
            self._photos[path] = ImageTk.PhotoImage(img)
        return self._photos[path]

    # -------------------------------------------------------------- Aktionen
    def _commit(self) -> None:
        """Übernimmt die Eingaben des aktuell angezeigten Schritts."""
        i = self._current
        if i is None or i >= len(self.steps):
            return
        step = self.steps[i]
        desc = " ".join(self._desc.get("1.0", "end").split())
        step.custom = desc if desc and desc != step.description() else None
        if step.kind == "text":
            step.text = self._txt.get("1.0", "end-1c")
        self._list.delete(i)
        self._list.insert(i, self._label(i, step))
        self._list.selection_set(i)

    def _move(self, delta: int) -> None:
        self._commit()
        i = self._current
        if i is None:
            return
        j = i + delta
        if not 0 <= j < len(self.steps):
            return
        self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
        self._refresh(select=j)

    def _delete(self) -> None:
        i = self._current
        if i is None:
            return
        del self.steps[i]
        self._current = None
        self._refresh(select=i)

    def _save(self) -> None:
        self._commit()
        if not self.steps:
            messagebox.showinfo("Keine Schritte", "Es sind keine Schritte mehr vorhanden.",
                                parent=self)
            return
        self.result = (self.steps, self._title.get().strip(),
                       self._intro.get("1.0", "end").strip())
        self.destroy()

    def _discard(self) -> None:
        if messagebox.askyesno("Verwerfen?", "Alle Schritte gehen verloren. Wirklich verwerfen?",
                               parent=self):
            self.result = None
            self.destroy()
