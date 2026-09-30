"""Tests der Klickziel-Beschreibung mit Attrappen statt echter UI Automation."""
from process_recorder import target
from process_recorder.target import (_clean_window_title, _clip, _region, describe_point,
                                     TargetResolver)


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class _Element:
    def __init__(self, password=False):
        self.CurrentIsPassword = 1 if password else 0


class Ctl:
    """Minimale Attrappe eines UI-Automation-Elements."""

    def __init__(self, type_name, name="", parent=None, help_text="", auto_id="", password=False,
                 pid=1, rect=None):
        self.ControlTypeName = type_name
        self.Name = name
        self.HelpText = help_text
        self.AutomationId = auto_id
        self.LocalizedControlType = ""
        self.ProcessId = pid
        self.BoundingRectangle = rect or Rect(0, 0, 1000, 800)
        self.Element = _Element(password)
        self._parent = parent
        self._children = []
        if parent is not None:
            parent._children.append(self)

    def GetParentControl(self):
        return self._parent

    def GetChildren(self):
        return list(self._children)

    def GetTopLevelControl(self):
        node = self
        while node._parent is not None and node._parent.ControlTypeName != "PaneControl_Desktop":
            node = node._parent
        return node


class FakeAuto:
    def __init__(self, control):
        self._control = control

    def ControlFromPoint(self, x, y):
        return self._control


def _window(title="Downloads – Datei-Explorer"):
    return Ctl("WindowControl", title)


def test_clip_shortens_and_normalizes_whitespace():
    assert _clip("  a \n b  ") == "a b"
    assert len(_clip("x" * 200)) == target.MAX_NAME_LEN
    assert _clip("x" * 200).endswith("…")


def test_clean_window_title_removes_tab_hint_and_app_suffix():
    assert _clean_window_title("Downloads und 3 weitere Registerkarten – Datei-Explorer",
                               "Datei-Explorer") == "Downloads"
    assert _clean_window_title("Unbenannt - Editor", "Editor") == "Unbenannt"
    assert _clean_window_title("Dokument1 - Word", "Word") == "Dokument1"


def test_clean_window_title_keeps_unrelated_suffix():
    assert _clean_window_title("Projekt - Notizen", "Editor") == "Projekt - Notizen"


def test_region_grid():
    rect = Rect(0, 0, 900, 600)
    assert _region(rect, 10, 10) == "oben links"
    assert _region(rect, 450, 300) == "Mitte"
    assert _region(rect, 890, 590) == "unten rechts"
    assert _region(rect, 450, 10) == "oben"
    assert _region(rect, 10, 300) == "links"


def test_region_handles_offset_and_out_of_range():
    rect = Rect(1000, 500, 1900, 1100)
    assert _region(rect, 1010, 510) == "oben links"
    assert _region(rect, 5000, 5000) == "unten rechts"          # wird begrenzt
    assert _region(Rect(0, 0, 0, 0), 1, 1) == ""


def test_describe_button_with_context(monkeypatch):
    monkeypatch.setattr(target, "_app_name", lambda pid: "Datei-Explorer")
    win = _window()
    bar = Ctl("AppBarControl", "", parent=win)
    button = Ctl("ButtonControl", "Umbenennen", parent=bar)
    text = describe_point(FakeAuto(button), 100, 50)
    assert text.startswith("Schaltfläche „Umbenennen“ (in Befehlsleiste)")
    assert "Datei-Explorer, Fenster „Downloads“" in text
    assert text.endswith("Position: oben links")


def test_describe_click_on_label_inside_button_targets_button(monkeypatch):
    monkeypatch.setattr(target, "_app_name", lambda pid: "Editor")
    win = _window("Unbenannt – Editor")
    button = Ctl("ButtonControl", "Speichern", parent=win)
    label = Ctl("TextControl", "Speichern", parent=button)
    text = describe_point(FakeAuto(label), 10, 10)
    assert text.startswith("Schaltfläche „Speichern“")


def test_describe_file_row_cell_reports_row_and_column(monkeypatch):
    monkeypatch.setattr(target, "_app_name", lambda pid: "Datei-Explorer")
    win = _window()
    row = Ctl("ListItemControl", "setup.exe", parent=win)
    cell = Ctl("EditControl", "Änderungsdatum", parent=row)
    text = describe_point(FakeAuto(cell), 10, 10)
    assert text.startswith("Listeneintrag „setup.exe“, Spalte „Änderungsdatum“")


def test_describe_password_field_never_reveals_name(monkeypatch):
    monkeypatch.setattr(target, "_app_name", lambda pid: "App")
    win = _window("Login")
    field = Ctl("EditControl", "Geheimes Kennwort", parent=win, password=True)
    assert describe_point(FakeAuto(field), 1, 1) == "Passwortfeld"


def test_describe_unlabeled_uses_known_id_or_parent(monkeypatch):
    monkeypatch.setattr(target, "_app_name", lambda pid: "Datei-Explorer")
    win = _window()
    group = Ctl("GroupControl", "", parent=win, auto_id="PART_BreadcrumbBar")
    assert "Pfadanzeige der Adressleiste" in describe_point(FakeAuto(group), 1, 1)

    split = Ctl("SplitButtonControl", "Downloads", parent=win)
    icon = Ctl("ButtonControl", "", parent=split)
    assert "gehört zu Schaltfläche „Downloads“" in describe_point(FakeAuto(icon), 1, 1)


def test_describe_none_when_nothing_under_cursor():
    assert describe_point(FakeAuto(None), 1, 1) is None


def test_resolver_returns_none_without_windows(monkeypatch):
    monkeypatch.setattr(target, "IS_WINDOWS", False)
    resolver = TargetResolver()
    assert resolver.submit(1, 1).result(timeout=1) is None


def test_resolver_skips_when_previous_query_is_stuck():
    resolver = TargetResolver()
    resolver._failed = False
    resolver._busy_since = target.time.monotonic() - target.STUCK_SECONDS - 1
    assert resolver.submit(1, 1).result(timeout=1) is None      # sofort, ohne zu warten
