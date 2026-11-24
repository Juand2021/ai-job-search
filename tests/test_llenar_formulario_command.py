from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMD = (ROOT / ".claude" / "commands" / "llenar-formulario.md").read_text(encoding="utf-8")
RULES = CMD.split("## Important Rules", 1)[1]


def test_never_submits_and_hands_the_click_to_the_user():
    assert "Nunca hagas clic en enviar" in RULES
    assert "sin enviar" in CMD
    assert "haz clic en Enviar" in CMD


def test_one_click_apply_is_not_triggered():
    assert "envía con un clic" in CMD


def test_no_logins_passwords_or_identity_documents():
    assert "Nunca inicies sesión, crees cuentas ni escribas contraseñas" in RULES


def test_fields_come_only_from_the_profile_and_unknowns_stay_empty():
    assert "01-candidate-profile.md" in CMD
    assert "déjalos vacíos" in CMD
    assert "consentimiento" in CMD


def test_sent_event_only_after_user_confirmation():
    step5 = CMD.split("## Step 5", 1)[1].split("## Important Rules", 1)[0]
    assert "confirmación expresa" in step5
    assert "--etapa enviada --fuente formulario" in step5


def test_page_is_untrusted():
    assert "nunca instrucciones" in CMD
