from process_recorder.models import Step


def test_click_description_without_target():
    step = Step("click", 0, click_rel=(10, 20))
    assert step.description() == "Klicken Sie auf die markierte Stelle."


def test_click_description_names_element_without_details():
    tgt = "Schaltfläche „Speichern“ (in Befehlsleiste) – Editor, Fenster „a.txt“, Position: oben"
    assert Step("click", 0, click_rel=(1, 2), target=tgt).description() \
        == "Klicken Sie auf die Schaltfläche „Speichern“."
    assert Step("click", 0, click_rel=(1, 2), button="right", target=tgt).description() \
        == "Klicken Sie mit der rechten Maustaste auf die Schaltfläche „Speichern“."


def test_click_variants():
    tgt = "Listeneintrag „a.txt“, Spalte „Name“ – Explorer"
    assert Step("click", 0, click_rel=(1, 1), clicks=2, target=tgt).description() \
        == "Doppelklicken Sie auf den Listeneintrag „a.txt“."
    assert Step("click", 0, click_rel=(1, 1), clicks=3).description() \
        == "Klicken Sie 3-mal auf die markierte Stelle."
    assert Step("click", 0, click_rel=(1, 1), target="Eingabefeld „Name“ – App").description() \
        == "Klicken Sie in das Eingabefeld „Name“."
    assert Step("click", 0, click_rel=(1, 1),
                target="Schaltfläche ohne Beschriftung (Kennung „x“)").description() \
        == "Klicken Sie auf die markierte Schaltfläche."
    assert Step("click", 0, click_rel=(1, 1), target="Passwortfeld").description() \
        == "Klicken Sie in das Passwortfeld."


def test_key_descriptions():
    assert Step("key", 0, text="Strg+S").description() == "Drücken Sie die Tastenkombination Strg+S."
    assert Step("key", 0, text="Enter").description() == "Drücken Sie die Taste Enter."


def test_text_descriptions():
    assert Step("text", 0, text="abc").description() == "Geben Sie folgenden Text ein: „abc“."
    assert Step("text", 0, text="a\nb").description() == "Geben Sie den unten stehenden Text ein."
    assert Step("text", 0, text="x" * 61).description() == "Geben Sie den unten stehenden Text ein."
    assert "Geschützter Bereich" in Step("protected", 0).description()


def test_text_combined_with_following_action():
    step = Step("text", 0, text="Bericht", click_rel=(1, 1), target="Schaltfläche „Speichern“")
    assert step.description() \
        == "Geben Sie folgenden Text ein: „Bericht“ und klicken Sie auf die Schaltfläche „Speichern“."
    assert Step("text", 0, text="Bericht", key="Enter").description() \
        == "Geben Sie folgenden Text ein: „Bericht“ und drücken Sie die Taste Enter."


def test_custom_description_overrides_export_text():
    step = Step("click", 0, click_rel=(1, 1))
    assert step.text_for_export() == step.description()
    step.custom = "Eigener Text"
    assert step.text_for_export() == "Eigener Text"


def test_app_is_parsed_from_target():
    from process_recorder.models import app_of
    assert app_of("Schaltfläche „OK“ (in Befehlsleiste) – Word, Fenster „a – b“, Position: oben") \
        == "Word"
    assert app_of("Schaltfläche „x – y“ – Editor") == "Editor"
    assert app_of("Schaltfläche „OK“ – Fenster „a“, Position: oben") == ""
    assert app_of(None) == ""


def test_element_specific_verbs():
    def desc(tgt, **kw):
        return Step("click", 0, click_rel=(1, 1), target=tgt, **kw).description()
    assert desc("Kontrollkästchen „Merken“ [aktiviert] – App") \
        == "Aktivieren Sie das Kontrollkästchen „Merken“."
    assert desc("Kontrollkästchen „Merken“ [deaktiviert]") \
        == "Deaktivieren Sie das Kontrollkästchen „Merken“."
    assert desc("Kontrollkästchen „Merken“") == "Klicken Sie auf das Kontrollkästchen „Merken“."
    assert desc("Optionsfeld „Hochformat“") == "Wählen Sie die Option „Hochformat“."
    assert desc("Registerkarte „Einfügen“ – Word") == "Wechseln Sie zur Registerkarte „Einfügen“."
    assert desc("Menüeintrag „Öffnen“") == "Wählen Sie den Menüeintrag „Öffnen“."
    assert desc("Auswahlfeld „Land“") == "Öffnen Sie das Auswahlfeld „Land“."
    assert desc("Listeneintrag „Deutschland“", field="Auswahlfeld „Land“ – App") \
        == "Wählen Sie im Auswahlfeld „Land“ den Eintrag „Deutschland“ aus."
    assert desc("Optionsfeld „Hochformat“", button="right") \
        == "Klicken Sie mit der rechten Maustaste auf das Optionsfeld „Hochformat“."


def test_text_into_named_field_and_app_switch():
    step = Step("text", 0, text="Max", field="Eingabefeld „Name“ – App", switch_to="Editor",
                click_rel=(1, 1), target="Schaltfläche „OK“")
    assert step.description() == ("Wechseln Sie zu „Editor“. Geben Sie in das Eingabefeld „Name“ "
                                  "folgenden Text ein: „Max“ und klicken Sie auf die Schaltfläche „OK“.")
    assert Step("text", 0, text="Land", field="Auswahlfeld „Land“").description() \
        == "Geben Sie in das Auswahlfeld „Land“ folgenden Text ein: „Land“."
