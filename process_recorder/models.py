"""Datenmodell eines aufgezeichneten Schritts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

BUTTON_NAMES = {"left": "Linksklick", "right": "Rechtsklick", "middle": "Mittelklick"}


@dataclass
class Step:
    """Ein Schritt der Anleitung: Klick, Texteingabe oder geschützter Bereich."""

    kind: str  # "click" | "text" | "key" | "protected"
    timestamp: float
    image_path: Optional[Path] = None          # Screenshot (JPEG im Temp-Ordner)
    click_rel: Optional[Tuple[int, int]] = None  # Klick relativ zum Monitor
    button: str = "left"
    clicks: int = 1                             # 2 = Doppelklick usw.
    text: str = ""
    target: Optional[str] = None                # per UI Automation ermitteltes Klickziel

    def description(self) -> str:
        """Automatisch erzeugte Kurzbeschreibung des Schritts."""
        if self.kind == "click" and self.click_rel:
            x, y = self.click_rel
            if self.clicks == 2:
                name = "Doppelklick"
            elif self.clicks > 2:
                name = f"{self.clicks}-fach-Klick"
            else:
                name = BUTTON_NAMES.get(self.button, "Klick")
            if self.target:
                return f"{name} auf {self.target} (Koordinate {x}, {y})"
            return f"{name} bei Koordinate ({x}, {y})"
        if self.kind == "text":
            return "Texteingabe"
        if self.kind == "key":
            return (f"Tastenkombination {self.text}" if "+" in self.text
                    else f"Taste {self.text}")
        return (
            "Geschützter Bereich (Administrator-Bestätigung / Passworteingabe): "
            "Die Aufnahme war pausiert, es wurden weder Eingaben noch Screenshots gespeichert."
        )
