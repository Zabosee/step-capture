# Process Recorder

Windows-Tool, das Mausklicks und Texteingaben aufzeichnet und daraus automatisch eine
Schritt-für-Schritt-Anleitung als Word-Datei (.docx) oder PDF erstellt, inklusive Screenshots mit
markierter Klickstelle.

## Funktionen
- Aufnahme auf einem frei wählbaren Monitor
- Jeder Schritt wird als kurze Handlungsanweisung formuliert, z. B. „Klicken Sie auf die
  Schaltfläche „Speichern“.“
- Zusammengehörige Aktionen (Feld anklicken, Text tippen, bestätigen) werden zu einem Schritt zusammengefasst
- Eigene Formulierungen für Kontrollkästchen, Optionsfelder, Registerkarten, Menüs und Auswahlfelder
- Tastenkürzel (Strg+S …), Enter, Esc, Entf und F-Tasten als eigene Schritte
- Screenshot mit rotem Kreis pro Klick, optional mit Zoom-Ausschnitt
- Editor: Schritte löschen, verschieben und beschriften, Abschnitte, Hinweise/Tipps/Warnungen,
  Titel, Einleitung und Abschluss
- Schutz sensibler Eingaben (siehe [Datenschutz](#datenschutz))

## Installation
**Exe:** Die fertige `ProcessRecorder.exe` gibt es unter
[Releases](../../releases). Sie benötigt keine Installation.

Beim ersten Start fragt Windows SmartScreen eventuell nach („Weitere Informationen“ →
„Trotzdem ausführen“). Das Programm läuft mit Administratorrechten (UAC-Abfrage), damit auch
Klicks in Admin-Fenstern wie Installern erfasst werden. Da es Tastatur und Maus mitliest, können
Virenscanner Fehlalarme melden. Den gesamten Quelltext findest du in diesem Repository.

**Aus dem Quelltext** (Python 3.12 empfohlen):
```
python -m pip install -r requirements.txt
python main.py
```

## Bedienung
1. Bildschirm wählen und **Start** klicken. Das Programmfenster am besten auf einen anderen
   Monitor schieben.
2. Den Ablauf durchführen.
3. **Aufnahme beenden** klicken, die Schritte in der Vorschau bearbeiten und als Word oder PDF speichern.

Globale Tastenkürzel: **Strg+Alt+R** Start/Ende, **Strg+Alt+P** Pause/Fortsetzen.

## Datenschutz
Nichts verlässt deinen Rechner. Es gibt keine Netzwerkzugriffe, Anleitungen werden nur lokal gespeichert.

Bei folgenden Situationen werden weder Text noch Screenshots aufgezeichnet:
- UAC-Abfragen (sicherer Desktop)
- Anmeldedialoge (credwiz, LogonUI)
- fokussierte Passwortfelder (Win32 `ES_PASSWORD` sowie UI Automation für Browser, WPF und UWP)

Zeichen der letzten 0,6 s vor der Erkennung werden verworfen. Im Dokument erscheint stattdessen
ein Hinweis-Schritt, danach läuft die Aufnahme automatisch weiter.

Die Screenshots zeigen alles, was auf dem Monitor zu sehen ist. Prüfe Anleitungen vor dem
Weitergeben auf private Inhalte.

## Grenzen
- Strg-Kombinationen (z. B. Strg+V) werden als Tastenkombination erfasst, der eingefügte Inhalt nicht.
- Passwortfelder in Browsern werden nur erkannt, wenn diese Barrierefreiheit (UIA) bereitstellen.
- Der Schutz funktioniert nur unter Windows.
- Der Screenshot entsteht kurz nach dem Klick, ein dadurch geöffnetes Menü kann schon sichtbar sein.

## Entwicklung
```
python -m pip install -r requirements.txt pytest
python -m pytest
```
Protokolldatei der App: `%APPDATA%\ProcessRecorder\log.txt`

Beiträge sind willkommen. Öffne gern ein Issue oder einen Pull Request.

## Lizenz
[MIT](LICENSE)
