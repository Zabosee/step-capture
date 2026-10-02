"""Datenmodell eines aufgezeichneten Schritts."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# XML-1.0-unzulässige Zeichen (Steuerzeichen, Surrogate, U+FFFE/FFFF): Fenster-/Elementnamen
# stammen aus fremden Programmen und würden sonst den Word-Export abbrechen lassen.
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def clean_text(text) -> str:
    """Entfernt Zeichen, die in Word/XML nicht darstellbar sind."""
    return _XML_INVALID.sub("", text or "")


# Bestimmter Artikel (Akkusativ) je Elementtyp für „Klicken Sie auf die Schaltfläche …“
ARTICLES = {
    "Schaltfläche": "die", "Eingabefeld": "das", "Menüeintrag": "den", "Menü": "das",
    "Menüleiste": "die", "Registerkarte": "die", "Kontrollkästchen": "das", "Optionsfeld": "das",
    "Link": "den", "Listeneintrag": "den", "Liste": "die", "Auswahlfeld": "das",
    "Baumeintrag": "den", "Tabellenzeile": "die", "Text": "den", "Bild": "das",
    "Symbolleiste": "die", "Befehlsleiste": "die", "Schieberegler": "den",
    "Bildlaufleiste": "die", "Titelleiste": "die", "Dokumentbereich": "den", "Bereich": "den",
    "Spaltenkopf": "den", "Zahlenfeld": "das", "Passwortfeld": "das", "Tabelle": "die",
}
# Felder, in die man hinein- statt daraufklickt
INTO_TYPES = {"Eingabefeld", "Passwortfeld", "Zahlenfeld", "Dokumentbereich", "Bereich"}
# Längere oder mehrzeilige Eingaben stehen nur im Kasten darunter, nicht im Satz
INLINE_TEXT_MAX = 60
NOTE_KINDS = ("Hinweis", "Tipp", "Warnung")

_NAMED = re.compile(r"^([^„(,–\[]+?) „(.+?)“")
_TOGGLE = re.compile(r"\[(aktiviert|deaktiviert)\]")
# „… – Word, Fenster „a.txt“, Position: oben“ → „Word“ (Programmnamen enthalten keine Kommas)
_APP = re.compile(r" – ([^„“,]+?)(?:, Fenster „.*)?(?:, Position: [^,]*)?$")


def element_kind(target: Optional[str]) -> str:
    """Elementtyp aus der Zielbeschreibung, z. B. „Schaltfläche“."""
    if not target:
        return ""
    match = _NAMED.match(target)
    return match.group(1) if match else re.split(r" ohne Beschriftung|[ ,(–\[]", target)[0]


def element_name(target: Optional[str]) -> str:
    """Beschriftung des Elements, z. B. „Speichern“ (leer, wenn unbeschriftet)."""
    match = _NAMED.match(target or "")
    return match.group(2) if match else ""


def app_of(target: Optional[str]) -> str:
    """Programmname aus der Zielbeschreibung, z. B. „Word“."""
    match = _APP.search(target or "")
    return match.group(1) if match else ""


def _element(target: Optional[str]) -> Tuple[str, str]:
    """Präposition und Element für den Satz, z. B. ("auf", "die Schaltfläche „OK“")."""
    kind, name = element_kind(target), element_name(target)
    article = ARTICLES.get(kind)
    prep = "in" if kind in INTO_TYPES else "auf"
    if name:
        return prep, f"{article} {kind} „{name}“" if article else f"„{name}“"
    if kind == "Passwortfeld":
        return prep, "das Passwortfeld"
    if article:
        return prep, f"{article} markierte {kind}"
    return "auf", "die markierte Stelle"


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
    key: str = ""                               # Texteingabe, abgeschlossen mit dieser Taste
    field: Optional[str] = None                 # zuvor angeklicktes Eingabe-/Auswahlfeld
    switch_to: str = ""                         # Programm, zu dem vorher gewechselt wird
    section: str = ""                           # Abschnittsüberschrift vor diesem Schritt
    note: str = ""                              # Hinweis/Tipp/Warnung zum Schritt
    note_kind: str = "Hinweis"

    def text_for_export(self) -> str:
        """Beschreibung für die Anleitung: eigene Fassung, sonst die automatische."""
        return clean_text(self.custom or self.description())

    def _click_phrase(self) -> str:
        """Klick als Satzteil, z. B. „klicken Sie auf die Schaltfläche „OK““."""
        prep, what = _element(self.target)
        if self.button == "right":
            return f"klicken Sie mit der rechten Maustaste {prep} {what}"
        if self.button == "middle":
            return f"klicken Sie mit der mittleren Maustaste {prep} {what}"
        if self.clicks == 2:
            return f"doppelklicken Sie {prep} {what}"
        if self.clicks > 2:
            return f"klicken Sie {self.clicks}-mal {prep} {what}"
        kind, name = element_kind(self.target), element_name(self.target)
        if element_kind(self.field) == "Auswahlfeld" and name:
            return (f"wählen Sie im Auswahlfeld „{element_name(self.field)}“ "
                    f"den Eintrag „{name}“ aus")
        if kind == "Kontrollkästchen":
            toggle = _TOGGLE.search(self.target or "")
            if toggle:
                verb = "aktivieren" if toggle.group(1) == "aktiviert" else "deaktivieren"
                return f"{verb} Sie {what}"
        if name:
            if kind == "Optionsfeld":
                return f"wählen Sie die Option „{name}“"
            if kind == "Registerkarte":
                return f"wechseln Sie zur Registerkarte „{name}“"
            if kind == "Menüeintrag":
                return f"wählen Sie den Menüeintrag „{name}“"
            if kind == "Auswahlfeld":
                return f"öffnen Sie das Auswahlfeld „{name}“"
        return f"klicken Sie {prep} {what}"

    def _key_phrase(self, key: str) -> str:
        return (f"drücken Sie die Tastenkombination {key}" if "+" in key
                else f"drücken Sie die Taste {key}")

    def _text_phrase(self) -> str:
        text = self.text.strip()
        where = ""
        if self.field:
            where = f" in {_element(self.field)[1]}"          # „in das Eingabefeld „Name““
        if "\n" in text or len(text) > INLINE_TEXT_MAX:
            phrase = f"geben Sie{where} den unten stehenden Text ein"
        else:
            phrase = f"geben Sie{where} folgenden Text ein: „{text}“"
        if self.click_rel:
            phrase += " und " + self._click_phrase()
        elif self.key:
            phrase += " und " + self._key_phrase(self.key)
        return phrase

    def description(self) -> str:
        """Automatisch erzeugte Handlungsanweisung, z. B. „Klicken Sie auf „Speichern“.“"""
        if self.kind == "click":
            phrase = self._click_phrase()
        elif self.kind == "key":
            phrase = self._key_phrase(self.text)
        elif self.kind == "text":
            phrase = self._text_phrase()
        else:
            return (
                "Geschützter Bereich (Administrator-Bestätigung / Passworteingabe): "
                "Die Aufnahme war pausiert, es wurden weder Eingaben noch Screenshots gespeichert."
            )
        sentence = phrase[0].upper() + phrase[1:] + "."
        return f"Wechseln Sie zu „{self.switch_to}“. {sentence}" if self.switch_to else sentence
