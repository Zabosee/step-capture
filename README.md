# Process Recorder

Zeichnet Mausklicks und Texteingaben auf einem gewählten Monitor auf und erzeugt daraus
eine Schritt-für-Schritt-Anleitung als Word-Datei (.docx) mit markierten Screenshots.

## Installation (Python 3.9+, Windows empfohlen)

```
pip install mss pillow pynput python-docx uiautomation
```
oder `pip install -r requirements.txt`. Start: `python main.py`

## Bedienung
1. Bildschirm wählen, **Start** klicken (Fenster am besten auf einen anderen Monitor schieben).
2. Ablauf durchführen. Klicks = Schritt mit Screenshot + rotem Kreis; zusammenhängender Text
   (beendet durch Tab, Enter oder Mausklick) = ein Textschritt.
3. **Stopp** klicken, Speicherort wählen – die Anleitung wird erzeugt.

## Sicherheits-Filter (nur Windows)
Keine Aufzeichnung von Text/Screenshots bei: UAC-Abfrage (sicherer Desktop, consent.exe),
Fenstern mit höheren Rechten als das Programm, fokussierten Passwortfeldern (Win32 `ES_PASSWORD`
sowie UI Automation für Browser/WPF/UWP). Zeichen der letzten 0,6 s vor Erkennung werden
verworfen. Im Dokument erscheint ein Hinweis-Schritt; danach läuft die Aufnahme automatisch weiter.

## Grenzen
- Strg-Kombinationen (z. B. Einfügen mit Strg+V) werden nicht als Text erfasst.
- Passwortfelder in Browsern werden nur erkannt, wenn diese Barrierefreiheit/UIA bereitstellen.
- Auf Nicht-Windows-Systemen ist der Schutz inaktiv.
