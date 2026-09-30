"""Datenmodell eines aufgezeichneten Schritts."""
from __future__ import annotations

import re
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
    custom: Optional[str] = None                # vom Nutzer überschriebene Beschreibung

    def headline(self) -> str:
        """Kurze Überschrift für die Anleitung, z. B. „Schaltfläche „Weiter“ anklicken“."""
        if self.kind == "click":
            match = re.match(r"^(.+?) „(.+?)“", self.target or "")
            what = f"{match.group(1)} „{match.group(2)}“" if match else None
            if self.button == "right":
                return f"Rechtsklick auf {what}" if what else "Rechtsklick"
            if self.button == "middle":
                return f"Mittelklick auf {what}" if what else "Mittelklick"
            if self.clicks == 2:
                return f"Doppelklick auf {what}" if what else "Doppelklick"
            if self.clicks > 2:
                return f"{self.clicks}-fach-Klick auf {what}" if what else f"{self.clicks}-fach-Klick"
            return f"{what} anklicken" if what else "Klick"
        if self.kind == "text":
            return "Text eingeben"
        if self.kind == "key":
            return (f"Tastenkombination {self.text} drücken" if "+" in self.text
                    else f"Taste {self.text} drücken")
        return "Geschützter Bereich"

    def text_for_export(self) -> str:
        """Beschreibung für die Anleitung: eigene Fassung, sonst die automatische."""
        return self.custom or self.description()

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
