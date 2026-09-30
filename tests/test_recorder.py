"""Tests der Aufnahme-Logik mit simulierten Ereignissen (ohne echte Hooks/Screenshots)."""
import sys
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
    r._redactor.submit = lambda: None
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
    assert rec.paused and rec.manual_paused and not rec.protected
    type_text(rec, "geheim")
    press(rec, Key.enter)
    rec._on_click(100, 100, SimpleNamespace(name="left"), True)
    events = queued(rec)
    assert [(e.kind, e.text) for e in events] == [("text", "vorher")]
    rec.set_manual_pause(False)
    assert not rec.paused
    rec._on_click(100, 100, SimpleNamespace(name="left"), True)
    assert [e.kind for e in queued(rec)] == ["click"]


def test_sensitive_context_blocks_input(rec):
    rec._detector.is_sensitive_fast = lambda: True
    rec._detector.reason = "Test"
    type_text(rec, "passwort")
    press(rec, Key.enter)
    rec._on_click(10, 10, SimpleNamespace(name="left"), True)
    kinds = [e.kind for e in queued(rec)]
    assert kinds == ["protected"] and rec.protected and rec.paused


def test_click_outside_monitor_and_inside_ignore_rect_are_skipped(tmp_path):
    r = Recorder(MONITOR, tmp_path, ignore_rect=lambda: (0, 0, 100, 100))
    r._detector.is_sensitive_fast = lambda: False
    r._resolver.submit = lambda x, y: None
    r._redactor.submit = lambda: None
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


def test_finish_redacts_backlog_before_closing_services(tmp_path, monkeypatch):
    """Nach dem Stopp müssen noch wartende Schritte geschwärzt werden (Dienste erst in finish schließen)."""
    r = Recorder(MONITOR, tmp_path)
    closed = []
    r._redactor.close = lambda: closed.append("redactor")
    r._resolver.close = lambda: closed.append("resolver")
    r._running = True
    r.begin_stop()
    assert closed == []                                   # begin_stop schließt nichts
    r._queue.get_nowait()                                 # Ende-Marker entfernen: kein Worker läuft hier
    r.finish()
    assert sorted(closed) == ["redactor", "resolver"]
