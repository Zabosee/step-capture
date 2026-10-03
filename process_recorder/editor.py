"""Vorschau-Editor: Schritte prüfen, löschen, umsortieren, Beschreibungen und Hinweise anpassen."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageTk

from .exporter import mark_click
from .gui import BG, BORDER, MUTED, SURFACE, TEXT
from .models import NOTE_KINDS, Step


class StepEditor(tk.Toplevel):
    """Modaler Dialog. Ergebnis in ``result``: (Schritte, Titel, Einleitung, Abschluss) oder None."""

    def __init__(self, master, steps: List[Step], scale: float) -> None:
        super().__init__(master, bg=BG)
        self.title("Anleitung prüfen und anpassen")
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self._scale = scale
        self.steps = list(steps)
        self.result: Optional[Tuple[List[Step], str, str, str]] = None
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
        px = self._px
        p8, p16 = px(8), px(16)
        root = ttk.Frame(self, padding=px(20))
        root.pack(fill="both", expand=True)

        # Kopf: Titel, Einleitung, Abschluss
        top = ttk.Frame(root)
        top.pack(fill="x")
        top.columnconfigure((0, 1), weight=1, uniform="texts")
        ttk.Label(top, text="Titel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._title = ttk.Entry(top)
        self._title.insert(0, "Prozessdokumentation")
        self._title.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(px(4), p8))
        ttk.Label(top, text="Einleitung (optional)").grid(row=2, column=0, sticky="w")
        ttk.Label(top, text="Abschluss (optional)").grid(row=2, column=1, sticky="w", padx=(p8, 0))
        self._intro = self._text_box(top, 2)
        self._intro.grid(row=3, column=0, sticky="ew", pady=(px(4), 0), padx=(0, p8))
        self._outro = self._text_box(top, 2)
        self._outro.grid(row=3, column=1, sticky="ew", pady=(px(4), 0), padx=(p8, 0))

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, pady=p16)

        # Links: Schrittliste + Aktionen
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        self._count = ttk.Label(left, style="Muted.TLabel")
        self._count.pack(anchor="w", pady=(0, px(4)))
        card = ttk.Frame(left, style="Card.TFrame")
        card.pack(fill="both", expand=True)
        screen_h = self.winfo_screenheight()
        rows = max(8, min(17, (screen_h - px(620)) // px(22)))
        self._list = tk.Listbox(card, width=44, height=rows, bd=0, activestyle="none",
                                exportselection=False, bg=SURFACE, fg=TEXT)
        scroll = ttk.Scrollbar(card, command=self._list.yview)
        self._list.configure(yscrollcommand=scroll.set)
        self._list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._list.bind("<<ListboxSelect>>", self._on_select)
        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=(p8, 0))
        for text, cmd in (("Nach oben", lambda: self._move(-1)),
                          ("Nach unten", lambda: self._move(1)), ("Löschen", self._delete)):
            ttk.Button(actions, text=text, command=cmd).pack(side="left", padx=(0, p8))

        # Rechts: Vorschau + Formular
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", padx=(p16, 0))
        right.columnconfigure(0, weight=1)
        self._img_w = px(520)
        self._img_h = max(px(180), min(px(300), int(screen_h * 0.3)))
        img_frame = tk.Frame(right, bg=BORDER, width=self._img_w, height=self._img_h)
        img_frame.grid(row=0, column=0)
        img_frame.pack_propagate(False)
        self._img_label = tk.Label(img_frame, bg=BORDER, fg=MUTED)
        self._img_label.pack(expand=True)

        def label(text: str, row: int) -> ttk.Label:
            lbl = ttk.Label(right, text=text)
            lbl.grid(row=row, column=0, sticky="w", pady=(p8, px(4)))
            return lbl

        label("Beschreibung", 1)
        self._desc = self._text_box(right, 3)
        self._desc.grid(row=2, column=0, sticky="ew")
        self._txt_caption = label("Eingegebener Text", 3)
        self._txt = self._text_box(right, 2)
        self._txt.grid(row=4, column=0, sticky="ew")
        note_head = ttk.Frame(right)
        note_head.grid(row=5, column=0, sticky="ew", pady=(p8, px(4)))
        ttk.Label(note_head, text="Hinweis (optional)").pack(side="left")
        self._note_kind = tk.StringVar(value=NOTE_KINDS[0])
        ttk.Combobox(note_head, textvariable=self._note_kind, values=NOTE_KINDS,
                     state="readonly", width=16).pack(side="right")
        self._note = self._text_box(right, 2)
        self._note.grid(row=6, column=0, sticky="ew")
        label("Abschnittsüberschrift (optional)", 7)
        self._section = ttk.Entry(right)
        self._section.grid(row=8, column=0, sticky="ew")

        # Fuß
        ttk.Separator(root).pack(fill="x")
        foot = ttk.Frame(root)
        foot.pack(fill="x", pady=(p16, 0))
        ttk.Button(foot, text="Weiter zum Speichern …", style="Primary.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(foot, text="Abbrechen", command=self._discard).pack(side="right", padx=(0, p8))

    def _text_box(self, master, height: int) -> tk.Text:
        box = tk.Text(master, height=height, width=60, wrap="word", padx=8, pady=6, undo=True)
        box.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
        return box

    # ----------------------------------------------------------- Liste/Anzeige
    @staticmethod
    def _label(index: int, step: Step) -> str:
        text = " ".join(step.text_for_export().split())
        if step.kind == "protected":
            text = "Geschützter Bereich (nicht aufgezeichnet)"
        mark = "▸ " if step.section else "  "
        return f"{index + 1:>3}  {mark}{text if len(text) <= 46 else text[:45] + '…'}"

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
        target = sel[0]
        self._commit()                           # ersetzt die Zeile des alten Schritts
        self._list.selection_clear(0, "end")
        self._list.selection_set(target)
        self._show(target)

    def _show(self, index: Optional[int]) -> None:
        self._current = index
        self._desc.delete("1.0", "end")
        self._txt.delete("1.0", "end")
        self._section.delete(0, "end")
        self._note.delete("1.0", "end")
        self._note_kind.set(NOTE_KINDS[0])
        step = None if index is None else self.steps[index]
        for w in (self._txt_caption, self._txt):
            (w.grid if step and step.kind == "text" else w.grid_remove)()
        if step is None:
            self._img_label.configure(image="", text="Keine Schritte")
            return
        self._desc.insert("1.0", step.text_for_export())
        self._section.insert(0, step.section)
        self._note.insert("1.0", step.note)
        self._note_kind.set(step.note_kind if step.note_kind in NOTE_KINDS else NOTE_KINDS[0])
        if step.kind == "text":
            self._txt.insert("1.0", step.text)
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
        step.section = " ".join(self._section.get().split())
        step.note = self._note.get("1.0", "end-1c").strip()
        step.note_kind = self._note_kind.get()
        self._list.delete(i)
        self._list.insert(i, self._label(i, step))

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
                       self._intro.get("1.0", "end").strip(), self._outro.get("1.0", "end").strip())
        self.destroy()

    def _discard(self) -> None:
        if messagebox.askyesno("Verwerfen?", "Alle Schritte gehen verloren. Wirklich verwerfen?",
                               parent=self):
            self.result = None
            self.destroy()
