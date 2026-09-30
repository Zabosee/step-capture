from process_recorder.models import Step


def test_click_description_without_target():
    step = Step("click", 0, click_rel=(10, 20))
    assert step.description() == "Linksklick bei Koordinate (10, 20)"


def test_click_description_with_target_and_button():
    step = Step("click", 0, click_rel=(1, 2), button="right", target="Schaltfläche „OK“ – Editor")
    assert step.description() == "Rechtsklick auf Schaltfläche „OK“ – Editor (Koordinate 1, 2)"


def test_double_and_multi_click_descriptions():
    assert Step("click", 0, click_rel=(1, 1), clicks=2).description().startswith("Doppelklick")
    assert Step("click", 0, click_rel=(1, 1), clicks=3).description().startswith("3-fach-Klick")


def test_key_descriptions():
    assert Step("key", 0, text="Strg+S").description() == "Tastenkombination Strg+S"
    assert Step("key", 0, text="Enter").description() == "Taste Enter"


def test_protected_and_text_descriptions():
    assert Step("text", 0, text="abc").description() == "Texteingabe"
    assert "Geschützter Bereich" in Step("protected", 0).description()


def test_headline_uses_target_kind_and_name():
    step = Step("click", 0, click_rel=(1, 1),
                target="Schaltfläche „Weiter“ (in Befehlsleiste) – Setup, Position: oben")
    assert step.headline() == "Schaltfläche „Weiter“ anklicken"


def test_headline_variants():
    tgt = "Listeneintrag „a.txt“, Spalte „Name“ – Explorer"
    assert Step("click", 0, click_rel=(1, 1), button="right", target=tgt).headline() \
        == "Rechtsklick auf Listeneintrag „a.txt“"
    assert Step("click", 0, click_rel=(1, 1), clicks=2, target=tgt).headline() \
        == "Doppelklick auf Listeneintrag „a.txt“"
    assert Step("click", 0, click_rel=(1, 1)).headline() == "Klick"
    assert Step("click", 0, click_rel=(1, 1), clicks=2).headline() == "Doppelklick"
    assert Step("text", 0, text="x").headline() == "Text eingeben"
    assert Step("key", 0, text="Strg+S").headline() == "Tastenkombination Strg+S drücken"
    assert Step("key", 0, text="F5").headline() == "Taste F5 drücken"
    assert Step("protected", 0).headline() == "Geschützter Bereich"


def test_custom_description_overrides_export_text():
    step = Step("click", 0, click_rel=(1, 1))
    assert step.text_for_export() == step.description()
    step.custom = "Eigener Text"
    assert step.text_for_export() == "Eigener Text"
