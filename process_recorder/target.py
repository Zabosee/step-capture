"""Ermittelt per UI Automation, worauf geklickt wurde (Element, Umgebung, Programm, Fenster).

UI Automation kann bei beschäftigten Zielprogrammen lange blockieren. Deshalb läuft die
Abfrage in einem eigenen Thread; der Aufrufer wartet nur begrenzt auf das Ergebnis.
"""
from __future__ import annotations

import contextlib
import logging
import queue
import re
import sys
import threading
import time
from concurrent.futures import Future
from typing import Optional, Tuple

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

TYPE_NAMES = {
    "ButtonControl": "Schaltfläche", "EditControl": "Eingabefeld",
    "MenuItemControl": "Menüeintrag", "MenuControl": "Menü", "MenuBarControl": "Menüleiste",
    "TabItemControl": "Registerkarte", "CheckBoxControl": "Kontrollkästchen",
    "RadioButtonControl": "Optionsfeld", "HyperlinkControl": "Link",
    "ListItemControl": "Listeneintrag", "ListControl": "Liste",
    "ComboBoxControl": "Auswahlfeld", "TreeItemControl": "Baumeintrag",
    "TreeControl": "Baumansicht", "DataItemControl": "Tabellenzeile",
    "SplitButtonControl": "Schaltfläche", "TextControl": "Text", "ImageControl": "Bild",
    "ToolBarControl": "Symbolleiste", "AppBarControl": "Befehlsleiste",
    "SliderControl": "Schieberegler", "ScrollBarControl": "Bildlaufleiste",
    "TitleBarControl": "Titelleiste", "DocumentControl": "Dokumentbereich",
    "PaneControl": "Bereich", "GroupControl": "Gruppe", "WindowControl": "Fenster",
    "TableControl": "Tabelle", "TabControl": "Registerkartenleiste",
    "HeaderControl": "Kopfzeile", "HeaderItemControl": "Spaltenkopf",
    "StatusBarControl": "Statusleiste", "ToolTipControl": "Kurzinfo",
    "SpinnerControl": "Zahlenfeld", "ProgressBarControl": "Fortschrittsbalken",
}
# Übergeordnete Elemente, die dem Leser helfen, die Stelle im Fenster zu finden
CONTEXT_TYPES = {
    "ToolBarControl", "AppBarControl", "MenuBarControl", "MenuControl", "ListControl",
    "TreeControl", "TabControl", "TableControl", "GroupControl", "HeaderControl",
    "StatusBarControl", "TitleBarControl", "PaneControl", "DataItemControl",
}
UNNAMED_CONTEXT_OK = {"ToolBarControl", "AppBarControl", "MenuBarControl", "TabControl",
                      "StatusBarControl", "TitleBarControl", "HeaderControl"}
APP_NAMES = {
    "explorer.exe": "Datei-Explorer", "chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Firefox", "notepad.exe": "Editor", "code.exe": "Visual Studio Code",
    "winword.exe": "Word", "excel.exe": "Excel", "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Outlook", "olk.exe": "Outlook", "cmd.exe": "Eingabeaufforderung",
    "powershell.exe": "PowerShell", "windowsterminal.exe": "Windows Terminal",
    "systemsettings.exe": "Einstellungen", "taskmgr.exe": "Task-Manager",
    "calculatorapp.exe": "Rechner", "mmc.exe": "Microsoft Management Console",
    "msiexec.exe": "Windows Installer", "teams.exe": "Microsoft Teams",
    "ms-teams.exe": "Microsoft Teams", "slack.exe": "Slack", "spotify.exe": "Spotify",
}
# Elemente, die selbst anklickbar sind; Klicks auf Text/Bild darin gelten dem Element
INTERACTIVE_TYPES = {
    "ButtonControl", "SplitButtonControl", "ListItemControl", "TabItemControl",
    "MenuItemControl", "TreeItemControl", "CheckBoxControl", "RadioButtonControl",
    "HeaderItemControl", "HyperlinkControl", "DataItemControl", "ComboBoxControl",
}
LEAF_TYPES = {"TextControl", "ImageControl", "PaneControl", "GroupControl", "EditControl"}
ROW_TYPES = {"ListItemControl", "DataItemControl"}
# Container ohne Aussagekraft für den Leser
NOISE_NAMES = {"steuerelementhost", "explorer-fenster", "ordnerlayoutbereich",
               "shellordneransicht", "desktop 1", "elementansicht"}
# Bekannte technische Kennungen unbeschrifteter Elemente → verständliche Bezeichnung
KNOWN_IDS = {
    "PART_BreadcrumbBar": "Pfadanzeige der Adressleiste", "PART_AutoSuggestBox": "Adressleiste",
    "FileExplorerSearchBox": "Suchfeld", "PART_BreadCrumbBarIcon": "Ordnersymbol der Adressleiste",
    "TabListView": "Registerkartenleiste", "TitleBar": "Titelleiste",
}
MAX_NAME_LEN = 80
STUCK_SECONDS = 1.5
_TABS_SUFFIX = re.compile(r"\s+und\s+\d+\s+weitere\s+Registerkarten?\b.*$", re.IGNORECASE)
_TITLE_SPLIT = re.compile(r"\s+[-–—]\s+")


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_NAME_LEN else text[:MAX_NAME_LEN - 1] + "…"


def _app_name(pid: int) -> str:
    """Anzeigename des Programms zum Prozess (z. B. „Datei-Explorer“)."""
    try:
        from .security import _process_info
        exe, _ = _process_info(pid)
    except Exception:
        exe = None
    if not exe:
        return ""
    if exe in APP_NAMES:
        return APP_NAMES[exe]
    stem = exe[:-4] if exe.endswith(".exe") else exe
    return stem.replace("_", " ").replace("-", " ").title()


def _clean_window_title(title: str, app: str) -> str:
    """„Downloads und 3 weitere Registerkarten – Datei-Explorer“ → „Downloads“."""
    title = _TABS_SUFFIX.sub("", title or "").strip()
    parts = _TITLE_SPLIT.split(title)
    if len(parts) > 1:
        last = parts[-1].strip().lower()
        # Programmname am Titelende ist Rauschen, weil er ohnehin separat genannt wird
        if last in ("explorer", "datei-explorer", "file explorer") or (
                app and (last in app.lower() or app.lower() in last)):
            title = " - ".join(parts[:-1])
    return _clip(title)


def _region(rect, x: int, y: int) -> str:
    """Grobe Lage des Klicks im Fenster: „oben links“, „Mitte“, „unten rechts“ …"""
    w, h = rect.width(), rect.height()
    if w <= 0 or h <= 0:
        return ""
    col = min(2, max(0, int((x - rect.left) * 3 / w)))
    row = min(2, max(0, int((y - rect.top) * 3 / h)))
    vert, horiz = ("oben", "", "unten")[row], ("links", "", "rechts")[col]
    return f"{vert} {horiz}".strip() or "Mitte"


def _label(control) -> Tuple[str, str]:
    """Beste Beschriftung (Name, Typ-Überschreibung): Name, Tooltip, sonst Kindelement."""
    name = _clip(control.Name)
    if name:
        return name, ""
    with contextlib.suppress(Exception):
        if control.HelpText:
            return _clip(control.HelpText), ""
    with contextlib.suppress(Exception):
        for child in control.GetChildren()[:6]:
            text = child.Name or ""
            ctype = child.ControlTypeName
            # Symbol-Glyphen (Private Use Area, z. B. Segoe-Icons) sind keine Beschriftung
            if (ctype in ("TextControl", "EditControl") and len(text.strip()) > 1
                    and not 0xE000 <= ord(text[0]) <= 0xF8FF):
                return _clip(text), (TYPE_NAMES[ctype] if ctype == "EditControl" else "")
    return "", ""


def _named_descendant(control, depth: int = 3) -> str:
    """Erster sinnvoller Name unterhalb eines unbeschrifteten Containers."""
    if depth == 0:
        return ""
    with contextlib.suppress(Exception):
        for child in control.GetChildren()[:8]:
            text = child.Name or ""
            if len(text.strip()) > 1 and not 0xE000 <= ord(text[0]) <= 0xF8FF:
                return _clip(text)
            found = _named_descendant(child, depth - 1)
            if found:
                return found
    return ""


def _unlabeled_hint(control) -> str:
    """Hinweis für Elemente ohne Namen: Bezug zu Nachbarn/Eltern oder technische ID."""
    with contextlib.suppress(Exception):
        if control.AutomationId in KNOWN_IDS:
            return f"{KNOWN_IDS[control.AutomationId]}"
    parent = control
    for _ in range(3):
        with contextlib.suppress(Exception):
            parent = parent.GetParentControl()
        if parent is None or parent.ControlTypeName == "WindowControl":
            break
        if parent.ControlTypeName in INTERACTIVE_TYPES and _clip(parent.Name):
            return f"gehört zu {TYPE_NAMES[parent.ControlTypeName]} „{_clip(parent.Name)}“"
    inner = _named_descendant(control)
    if inner:
        return f"enthält „{inner}“"
    with contextlib.suppress(Exception):
        if control.AutomationId:
            return f"Kennung „{control.AutomationId}“"
    return ""


def _context(control, top, name: str, window: str, type_name: str) -> str:
    """Nächste aussagekräftige übergeordnete Elemente, z. B. „Liste „Elementansicht““."""
    found = []                                   # (Typ, Name)
    parent = control
    for _ in range(10):
        with contextlib.suppress(Exception):
            parent = parent.GetParentControl()
        if parent is None or (top is not None and parent == top):
            break
        ptype = parent.ControlTypeName
        if ptype == "WindowControl":
            break
        if ptype not in CONTEXT_TYPES:
            continue
        pname = _clip(parent.Name)
        if pname.lower() in NOISE_NAMES or pname == TYPE_NAMES.get(ptype):
            pname = ""                            # z. B. „Statusleiste „Statusleiste““
        if pname:
            if pname not in (name, window) and pname not in [n for _, n in found]:
                found.append((ptype, pname))
        elif (ptype in UNNAMED_CONTEXT_OK and ptype != type_name
              and ptype not in [t for t, n in found if not n]):
            found.append((ptype, ""))
        if len(found) == 2:
            break
    return ", ".join(f"{TYPE_NAMES.get(t, t)} „{n}“" if n else TYPE_NAMES.get(t, t)
                     for t, n in found)


def describe_point(auto, x: int, y: int) -> Optional[str]:
    """Beschreibung des Elements bei (x, y).

    Beispiel: Schaltfläche „Umbenennen“ (in Befehlsleiste) – Datei-Explorer,
    Fenster „Downloads“ (oben links)
    """
    control = auto.ControlFromPoint(x, y)
    if control is None:
        return None
    type_name = control.ControlTypeName or ""
    kind = (TYPE_NAMES.get(type_name) or _clip(getattr(control, "LocalizedControlType", ""))
            or "Element")
    is_password = False
    with contextlib.suppress(Exception):
        is_password = bool(control.Element.CurrentIsPassword)
    if is_password:
        return "Passwortfeld"                    # nie Namen/Inhalt eines Passwortfelds auslesen

    # Klick auf Text/Bild/Zelle innerhalb eines Elements → das Element beschreiben
    cell = ""
    if type_name in LEAF_TYPES:
        leaf, leaf_name = control, _clip(control.Name)
        node = control
        for _ in range(4):
            with contextlib.suppress(Exception):
                node = node.GetParentControl()
            if node is None or node.ControlTypeName == "WindowControl":
                break
            if node.ControlTypeName in INTERACTIVE_TYPES:
                if type_name == "EditControl" and node.ControlTypeName in ROW_TYPES:
                    cell = leaf_name                  # Spalte einer Datei-/Tabellenzeile
                control = node
                type_name = node.ControlTypeName
                kind = TYPE_NAMES.get(type_name, kind)
                break

    name, kind_override = _label(control)
    kind = kind_override or kind

    # Top-Level-Fenster, Programm und Lage des Klicks
    window = app = region = ""
    top = None
    with contextlib.suppress(Exception):
        top = control.GetTopLevelControl()
    if top is not None:
        with contextlib.suppress(Exception):
            app = _app_name(top.ProcessId)
        with contextlib.suppress(Exception):
            window = _clean_window_title(top.Name, app)
        with contextlib.suppress(Exception):
            region = _region(top.BoundingRectangle, x, y)

    if name:
        text = f"{kind} „{name}“"
    else:
        hint = _unlabeled_hint(control)
        text = f"{kind} ohne Beschriftung" + (f" ({hint})" if hint else "")
    if cell:
        text += f", Spalte „{cell}“"
    context = _context(control, top, name, window, type_name)
    if context:
        text += f" (in {context})"
    where = [app] if app else []
    if window and window != name:
        where.append(f"Fenster „{window}“")
    if region:
        where.append(f"Position: {region}")
    if where:
        text += " – " + ", ".join(where)
    return text


class TargetResolver:
    """Beantwortet Abfragen (x, y) → Beschreibung in einem eigenen UI-Automation-Thread."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[Optional[Tuple[int, int, Future]]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._failed = not IS_WINDOWS
        self._busy_since: Optional[float] = None     # gesetzt, solange eine Abfrage läuft

    def submit(self, x: int, y: int) -> "Future[Optional[str]]":
        fut: "Future[Optional[str]]" = Future()
        busy = self._busy_since
        if self._failed or (busy is not None and time.monotonic() - busy > STUCK_SECONDS):
            fut.set_result(None)                 # Zielprogramm hängt: nicht auch noch warten
            return fut
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        self._queue.put((x, y, fut))
        return fut

    def close(self) -> None:
        self._queue.put(None)

    def _loop(self) -> None:
        try:
            import uiautomation as auto
            init = auto.UIAutomationInitializerInThread()
        except Exception:
            log.warning("UI Automation nicht verfügbar – Klickziele werden nicht ermittelt.")
            self._failed = True
            self._drain()
            return
        with init:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                x, y, fut = item
                self._busy_since = time.monotonic()
                try:
                    fut.set_result(describe_point(auto, x, y))
                except Exception:
                    log.debug("Klickziel konnte nicht ermittelt werden", exc_info=True)
                    fut.set_result(None)
                finally:
                    self._busy_since = None

    def _drain(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if item:
                item[2].set_result(None)
