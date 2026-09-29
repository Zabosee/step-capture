# Process Recorder

Zeichnet Mausklicks und Texteingaben auf einem gewählten Monitor auf und erzeugt daraus
eine Schritt-für-Schritt-Anleitung als Word-Datei (.docx) mit markierten Screenshots.

Hinweise: Die exe ist nicht signiert, Windows SmartScreen fragt beim ersten Start nach
(„Weitere Informationen“ → „Trotzdem ausführen“). Da das Programm Tastatur und Maus mitliest,
können Virenscanner einen Fehlalarm auslösen.

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
- Der Screenshot entsteht kurz nach dem Klick; ein dadurch geöffnetes Menü kann bereits sichtbar sein.

---
Made by Lukas Dostal
