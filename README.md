# Process Recorder

Zeichnet Mausklicks und Texteingaben auf einem gewählten Monitor auf und erzeugt daraus
eine Schritt-für-Schritt-Anleitung als Word-Datei (.docx) oder PDF mit markierten Screenshots.

Hinweise: Die exe ist nicht signiert (siehe „Exe signieren“ unten), Windows SmartScreen fragt beim ersten Start nach
(„Weitere Informationen“ → „Trotzdem ausführen“). Da das Programm Tastatur und Maus mitliest,
können Virenscanner einen Fehlalarm auslösen.

## Bedienung
1. Bildschirm wählen, **Start** klicken (Fenster am besten auf einen anderen Monitor schieben).
2. Ablauf durchführen. Jeder Schritt wird als kurze Handlungsanweisung formuliert, z. B.
   „Klicken Sie auf die Schaltfläche „Speichern“.“ oder „Geben Sie in das Eingabefeld „Name“
   folgenden Text ein: „Max“ und klicken Sie auf die Schaltfläche „OK“.“ Klick ins Feld, Tippen und
   der abschließende Klick bzw. Enter werden zu einem Schritt zusammengefasst; Kontrollkästchen,
   Optionsfelder, Registerkarten, Menüs und Auswahlfelder haben eigene Formulierungen, ein
   Programmwechsel wird vermerkt. Tastenkürzel (Strg+S …), Enter, Esc, Entf und F-Tasten sind
   eigene Schritte. Jeder Klick-Schritt bekommt einen Screenshot mit rotem Kreis.
3. **Aufnahme beenden** klicken. In der Vorschau lassen sich Schritte löschen, verschieben und
   beschriften, Abschnitte beginnen, Hinweise/Tipps/Warnungen zu Schritten ergänzen sowie Titel,
   Einleitung und Abschluss setzen. Danach Speicherort und Format (Word oder PDF) wählen.

Tastenkürzel (global): **Strg+Alt+R** Start/Ende, **Strg+Alt+P** Pause/Fortsetzen. Die Option
„Zoom-Ausschnitt um jeden Klick einfügen“ ergänzt unter dem Screenshot einen Zoom-Ausschnitt.

## Entwicklung
`python -m pip install -r requirements.txt pytest` und `python -m pytest` (Tests in `tests/`).
Protokolldatei der App: `%APPDATA%\ProcessRecorder\log.txt`.

## Sicherheits-Filter (nur Windows)
Keine Aufzeichnung von Text/Screenshots bei: UAC-Abfrage (sicherer Desktop, consent.exe),
Anmeldedialogen (credwiz, LogonUI), fokussierten Passwortfeldern (Win32 `ES_PASSWORD`
sowie UI Automation für Browser/WPF/UWP). Zeichen der letzten 0,6 s vor Erkennung werden
verworfen. Im Dokument erscheint ein Hinweis-Schritt; danach läuft die Aufnahme automatisch weiter (auch wenn danach ein Programm mit Adminrechten, z. B. ein Installer, im Vordergrund läuft).

Hinweis: Die exe startet mit Administratorrechten (UAC-Abfrage beim Start). Nur so kann Windows Klicks und Eingaben in Admin-Fenstern (z. B. Installern) an den Recorder melden.

## Grenzen
- Strg-Kombinationen (z. B. Einfügen mit Strg+V) werden als Tastenkombination-Schritt erfasst,
  nicht als Text; der eingefügte Inhalt selbst wird nicht aufgezeichnet.
- Passwortfelder in Browsern werden nur erkannt, wenn diese Barrierefreiheit/UIA bereitstellen.
- Auf Nicht-Windows-Systemen ist der Schutz inaktiv.
- Der Screenshot entsteht kurz nach dem Klick; ein dadurch geöffnetes Menü kann bereits sichtbar sein.

## Exe signieren (optional)
Der Build signiert `ProcessRecorder.exe` automatisch, sobald im GitHub-Repo (Settings > Secrets and variables > Actions) zwei Secrets existieren:
- `WINDOWS_CERT_PFX_BASE64`: das Code-Signing-Zertifikat als PFX, base64-kodiert (PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))`)
- `WINDOWS_CERT_PASSWORD`: das PFX-Passwort

Ohne Secrets wird der Schritt übersprungen und die exe bleibt unsigniert. Die Signatur enthält einen RFC-3161-Zeitstempel (DigiCert). Ein Zertifikat muss bei einer Zertifizierungsstelle gekauft werden (OV/EV); SmartScreen-Warnungen verschwinden bei OV erst nach und nach, bei EV sofort.
