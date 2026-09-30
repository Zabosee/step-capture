"""Tests der reinen Logik des Schwärzens (ohne UI Automation)."""
import time

import pytest
from PIL import Image

from process_recorder import redaction
from process_recorder.redaction import (RedactionFinder, is_sensitive_name, redact_image,
                                        to_image_rects)


@pytest.mark.parametrize("name, auto_id", [
    ("Kennwort", ""), ("Passwort eingeben", ""), ("Password", ""), ("", "txtPassword"),
    ("", "user_password"), ("PIN", ""), ("PIN-Code", ""), ("", "pinField"), ("API-Key", ""),
    ("", "apiKey"), ("API Key", ""), ("Token", ""), ("Secret", ""), ("Client Secret", ""),
    ("IBAN", ""), ("", "IbanInput"), ("Kreditkartennummer", ""), ("Credit Card Number", ""),
    ("CVV", ""), ("Geheimzahl", ""),
])
def test_sensitive_names(name, auto_id):
    assert is_sensitive_name(name, auto_id)


@pytest.mark.parametrize("name, auto_id", [
    ("Suchfeld", ""), ("Benutzername", "userName"), ("E-Mail", ""), ("Spinner", ""),
    ("Pinterest", ""), ("Pipeline", ""), ("Adresse und Suchleiste", "urlbar"), ("", ""),
    ("Tangente", ""), ("Station", ""),
])
def test_normal_names(name, auto_id):
    assert not is_sensitive_name(name, auto_id)


MON = {"left": 0, "top": 0, "width": 200, "height": 100}


def test_rects_relative_to_monitor_offset():
    mon = {"left": 1920, "top": 0, "width": 200, "height": 100}
    out = to_image_rects([(1920 + 50, 20, 1920 + 150, 40)], mon, (200, 100))
    p = redaction.PADDING
    assert out == [(50 - p, 20 - p, 150 + p, 40 + p)]


def test_rects_negative_monitor_origin():
    mon = {"left": -1920, "top": -100, "width": 200, "height": 100}
    out = to_image_rects([(-1900, -90, -1800, -70)], mon, (200, 100))
    p = redaction.PADDING
    assert out == [(20 - p, 10 - p, 120 + p, 30 + p)]


def test_rects_clipped_and_outside_dropped():
    out = to_image_rects([(-50, -50, 30, 30), (300, 10, 400, 40), (10, 10, 11, 11)],
                         MON, (200, 100))
    assert out == [(0, 0, 32, 32)]           # zweites außerhalb, drittes zu klein


def test_rects_scaled_when_image_differs():
    out = to_image_rects([(50, 20, 100, 40)], MON, (400, 200))     # Bild doppelt so groß
    p = redaction.PADDING
    assert out == [(100 - p, 40 - p, 200 + p, 80 + p)]


def test_redact_image_fills_only_rects():
    img = Image.new("RGB", (100, 50), (255, 255, 255))
    redact_image(img, [(10, 10, 30, 20)])
    assert img.getpixel((10, 10)) == (0, 0, 0)
    assert img.getpixel((29, 19)) == (0, 0, 0)
    assert img.getpixel((30, 19)) == (255, 255, 255)
    assert img.getpixel((5, 5)) == (255, 255, 255)


def test_redact_image_without_rects_unchanged():
    img = Image.new("RGB", (20, 20), (10, 20, 30))
    before = img.tobytes()
    assert redact_image(img, []).tobytes() == before


def test_finder_returns_rects_from_injected_search():
    f = RedactionFinder(finder=lambda client: [(1, 2, 30, 40)])
    if f._failed:
        pytest.skip("UI Automation nicht verfügbar")
    assert f.result(f.submit(), timeout=5) == [(1, 2, 30, 40)]
    f.close()


def test_finder_timeout_and_error_give_none():
    def slow(_client):
        time.sleep(1.0)
        return [(0, 0, 10, 10)]
    f = RedactionFinder(finder=slow)
    if f._failed:
        pytest.skip("UI Automation nicht verfügbar")
    t = time.perf_counter()
    assert f.result(f.submit(), timeout=0.2) is None
    assert time.perf_counter() - t < 0.6

    def broken(_client):
        raise RuntimeError("Zielprogramm kaputt")
    g = RedactionFinder(finder=broken)
    assert g.result(g.submit(), timeout=5) is None
