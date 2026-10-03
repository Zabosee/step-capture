"""Tests der Aufnahme-Logik mit simulierten Ereignissen (ohne echte Hooks/Screenshots)."""
import sys
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

pytest.importorskip("pynput")
if sys.platform != "win32":
    pytest.skip("Recorder-Tests benötigen Windows", allow_module_level=True)

from pynput.keyboard import Key, KeyCode

from process_recorder import recorder as rec_mod
from process_recorder.models import Step
from process_recorder.recorder import Recorder

MONITOR = {"left": 0, "top": 0, "width": 1920, "height": 1200}


@pytest.fixture
def rec(tmp_path):
    r = Recorder(MONITOR, tmp_path)
    r._detector.is_sensitive_fast = lambda: False          # keine echten Windows-Abfragen
    r._resolver.submit = lambda x, y: None                 # keine UI Automation
    return r


def press(rec, *keys):
    for k in keys:
        rec._on_key_press(k)


def release(rec, *keys):
    for k in reversed(keys):
        rec._on_key_release(k)


def type_text(rec, text):
    for ch in text:
        rec._on_key_press(KeyCode.from_char(ch))
        rec._on_key_release(KeyCode.from_char(ch))


def queued(rec):
    events = []
    while not rec._queue.empty():
        events.append(rec._queue.get_nowait())
    return events


def test_typed_text_becomes_one_text_event_on_enter(rec):
    type_text(rec, "Hallo")
    press(rec, Key.enter)
    events = queued(rec)
    assert [(e.kind, e.text) for e in events] == [("text", "Hallo"), ("key", "Enter")]


def test_backspace_and_space_edit_buffer(rec):
    type_text(rec, "abx")
    press(rec, Key.backspace)
    press(rec, Key.space)
    type_text(rec, "c")
    rec._flush_text()
    assert [(e.kind, e.text) for e in queued(rec)] == [("text", "ab c")]


def test_ctrl_shortcut_is_recorded_not_typed(rec):
    press(rec, Key.ctrl_l)
    rec._on_key_press(KeyCode.from_vk(0x53))               # Strg+S (ohne Zeichen, nur Tastencode)
    release(rec, Key.ctrl_l)
    assert [(e.kind, e.text) for e in queued(rec)] == [("key", "Strg+S")]


def test_shortcut_with_shift_and_alt_labels(rec):
    press(rec, Key.ctrl_l, Key.shift)
    rec._on_key_press(KeyCode.from_vk(0x53))
    release(rec, Key.ctrl_l, Key.shift)
    press(rec, Key.alt_l)
    rec._on_key_press(KeyCode.from_vk(0x46))
    release(rec, Key.alt_l)
    assert [e.text for e in queued(rec)] == ["Strg+Umschalt+S", "Alt+F"]


def test_shortcut_flushes_pending_text_first(rec):
    type_text(rec, "abc")
    press(rec, Key.ctrl_l)
    rec._on_key_press(KeyCode.from_vk(0x56))
    release(rec, Key.ctrl_l)
    assert [(e.kind, e.text) for e in queued(rec)] == [("text", "abc"), ("key", "Strg+V")]


def test_function_and_special_keys(rec):
    press(rec, Key.f5, Key.esc, Key.delete)
    assert [e.text for e in queued(rec)] == ["F5", "Esc", "Entf"]


def test_tab_only_flushes_text(rec):
    type_text(rec, "x")
    press(rec, Key.tab)
    assert [(e.kind, e.text) for e in queued(rec)] == [("text", "x")]


def test_altgr_characters_count_as_text(rec):
    press(rec, Key.ctrl_l, Key.alt_gr)                     # Windows meldet AltGr als Strg+AltGr
    rec._on_key_press(KeyCode.from_char("@"))
    release(rec, Key.ctrl_l, Key.alt_gr)
    rec._flush_text()
    assert [(e.kind, e.text) for e in queued(rec)] == [("text", "@")]


def test_app_hotkeys_are_never_recorded(rec):
    for vk in (ord(rec_mod.HOTKEY_TOGGLE.upper()), ord(rec_mod.HOTKEY_PAUSE.upper())):
        press(rec, Key.ctrl_l, Key.alt_l)
        rec._on_key_press(KeyCode.from_vk(vk))
        release(rec, Key.ctrl_l, Key.alt_l)
    rec._flush_text()
    assert queued(rec) == []


def test_manual_pause_ignores_keys_and_clicks_but_keeps_earlier_text(rec):
    type_text(rec, "vorher")
    rec.set_manual_pause(True)
    assert rec.manual_paused and not rec.protected
    type_text(rec, "geheim")
    press(rec, Key.enter)
    rec._on_click(100, 100, SimpleNamespace(name="left"), True)
    events = queued(rec)
    assert [(e.kind, e.text) for e in events] == [("text", "vorher")]
    rec.set_manual_pause(False)
    assert not rec.manual_paused
    rec._on_click(100, 100, SimpleNamespace(name="left"), True)
    assert [e.kind for e in queued(rec)] == ["click"]


def test_sensitive_context_blocks_input(rec):
    rec._detector.is_sensitive_fast = lambda: True
    rec._detector.reason = "Test"
    type_text(rec, "passwort")
    press(rec, Key.enter)
    rec._on_click(10, 10, SimpleNamespace(name="left"), True)
    kinds = [e.kind for e in queued(rec)]
    assert kinds == ["protected"] and rec.protected


def test_click_outside_monitor_and_inside_ignore_rect_are_skipped(tmp_path):
    r = Recorder(MONITOR, tmp_path, ignore_rect=lambda: (0, 0, 100, 100))
    r._detector.is_sensitive_fast = lambda: False
    r._resolver.submit = lambda x, y: None
    r._on_click(50, 50, SimpleNamespace(name="left"), True)         # Recorder-Fenster
    r._on_click(5000, 50, SimpleNamespace(name="left"), True)       # anderer Monitor
    r._on_click(500, 500, SimpleNamespace(name="left"), False)      # Loslassen
    assert queued(r) == []
    r._on_click(500, 500, SimpleNamespace(name="left"), True)
    assert [e.kind for e in queued(r)] == [("click")]


def test_double_click_is_merged_into_one_step(rec, monkeypatch, tmp_path):
    monkeypatch.setattr(rec, "_grab", lambda sct, pending=None: tmp_path / "x.jpg")
    ev1 = rec_mod._Event("click", 100.0, x=200, y=300, button="left")
    ev2 = rec_mod._Event("click", 100.2, x=203, y=301, button="left")
    ev3 = rec_mod._Event("click", 101.5, x=203, y=301, button="left")   # zu spät: neuer Schritt
    for ev in (ev1, ev2, ev3):
        rec._handle_event(None, ev)
    assert [(s.kind, s.clicks) for s in rec.steps] == [("click", 2), ("click", 1)]


def test_text_is_merged_with_following_click_or_key(rec, monkeypatch, tmp_path):
    monkeypatch.setattr(rec, "_grab", lambda sct, pending=None: tmp_path / "x.jpg")
    for ev in (rec_mod._Event("text", 1.0, text="Bericht"),
               rec_mod._Event("click", 1.1, x=200, y=300, button="left"),
               rec_mod._Event("text", 2.0, text="Suche"),
               rec_mod._Event("key", 2.1, text="Enter"),
               rec_mod._Event("key", 3.0, text="Strg+S")):
        rec._handle_event(None, ev)
    assert [(s.kind, s.text, s.key) for s in rec.steps] \
        == [("text", "Bericht", ""), ("text", "Suche", "Enter"), ("key", "Strg+S", "")]
    assert rec.steps[0].click_rel == (200, 300)


def _click(ts, x, target):
    fut = Future()
    fut.set_result(target)
    return rec_mod._Event("click", ts, x=x, y=300, button="left", target=fut)


def test_click_into_field_is_merged_with_typing(rec, monkeypatch, tmp_path):
    monkeypatch.setattr(rec, "_grab", lambda sct, pending=None: tmp_path / "x.jpg")
    for ev in (_click(1.0, 100, "Eingabefeld „Name“ – Editor"),
               rec_mod._Event("text", 2.0, text="Max"),
               _click(3.0, 500, "Schaltfläche „OK“ – Editor"),
               _click(4.0, 600, "Eingabefeld ohne Beschriftung – Editor"),
               rec_mod._Event("text", 5.0, text="frei")):
        rec._handle_event(None, ev)
    first, second, third = rec.steps
    assert (first.kind, first.field, first.target, first.click_rel) \
        == ("text", "Eingabefeld „Name“ – Editor", "Schaltfläche „OK“ – Editor", (500, 300))
    assert first.switch_to == "Editor" and not second.switch_to
    assert (second.kind, third.kind, third.field) == ("click", "text", None)   # unbeschriftet


def test_dropdown_selection_is_one_step(rec, monkeypatch, tmp_path):
    monkeypatch.setattr(rec, "_grab", lambda sct, pending=None: tmp_path / "x.jpg")
    for ev in (_click(1.0, 100, "Auswahlfeld „Land“ – App"),
               _click(2.0, 400, "Listeneintrag „Deutschland“ – App"),
               _click(3.0, 700, "Listeneintrag „Österreich“ – App")):
        rec._handle_event(None, ev)
    assert [s.description() for s in rec.steps] == [
        "Wechseln Sie zu „App“. Wählen Sie im Auswahlfeld „Land“ den Eintrag „Deutschland“ aus.",
        "Klicken Sie auf den Listeneintrag „Österreich“."]


def test_app_switch_is_noted_once_per_change(rec, monkeypatch, tmp_path):
    monkeypatch.setattr(rec, "_grab", lambda sct, pending=None: tmp_path / "x.jpg")
    for i, tgt in enumerate(["Schaltfläche „A“ – Word", "Schaltfläche „B“ – Word",
                             "Schaltfläche „Word“ (in Taskleiste) – Datei-Explorer",
                             "Schaltfläche „C“ – Excel"]):
        rec._handle_event(None, _click(float(i * 5), i * 100, tgt))
    assert [s.switch_to for s in rec.steps] == ["Word", "", "", "Excel"]


def test_protected_steps_are_merged(rec):
    for ts in (1.0, 2.0):
        rec._handle_event(None, rec_mod._Event("protected", ts, capture=False))
    assert [s.kind for s in rec.steps] == ["protected"]


def test_key_event_creates_key_step(rec, monkeypatch, tmp_path):
    monkeypatch.setattr(rec, "_grab", lambda sct, pending=None: tmp_path / "k.jpg")
    rec._handle_event(None, rec_mod._Event("key", 1.0, text="Strg+S"))
    assert rec.steps[0].kind == "key" and rec.steps[0].text == "Strg+S"
    assert isinstance(rec.steps[0], Step)


def test_key_label_mapping():
    assert Recorder._key_label(Key.enter) == "Enter"
    assert Recorder._key_label(Key.f12) == "F12"
    assert Recorder._key_label(KeyCode.from_vk(0x41)) == "A"
    assert Recorder._key_label(KeyCode.from_char("é")) == "É"
    assert Recorder._key_label(Key.shift) is None


def test_finish_closes_services(tmp_path):
    r = Recorder(MONITOR, tmp_path)
    closed = []
    r._resolver.close = lambda: closed.append("resolver")
    r._running = True
    r.begin_stop()
    assert closed == []                                   # begin_stop schließt nichts
    r._queue.get_nowait()                                 # Ende-Marker entfernen: kein Worker läuft hier
    r.finish()
    assert closed == ["resolver"]
