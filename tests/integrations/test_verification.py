from app.config.settings import Settings


def test_vexen_verification_defaults_to_current_contract(monkeypatch):
    for key in (
        "VEXEN_VERIFICATION_INTEGRATION",
        "VERIFICATION_INTEGRATION",
        "VEXEN_VERIFICATION_SCHEMA",
        "VEXMOD_ROLES_SCHEMA",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)
    assert settings.verification_integration == "postgres"
    assert settings.vexen_verification_schema == "vexen_verification"


def test_new_vexen_environment_names(monkeypatch):
    monkeypatch.setenv("VEXEN_VERIFICATION_INTEGRATION", "disabled")
    monkeypatch.setenv("VEXEN_VERIFICATION_SCHEMA", "vexen_verification_test")
    settings = Settings(_env_file=None)
    assert settings.verification_integration == "disabled"
    assert settings.vexen_verification_schema == "vexen_verification_test"


def test_legacy_environment_names_are_temporarily_accepted(monkeypatch):
    monkeypatch.delenv("VEXEN_VERIFICATION_INTEGRATION", raising=False)
    monkeypatch.delenv("VEXEN_VERIFICATION_SCHEMA", raising=False)
    monkeypatch.setenv("VERIFICATION_INTEGRATION", "disabled")
    monkeypatch.setenv("VEXMOD_ROLES_SCHEMA", "legacy_roles")
    settings = Settings(_env_file=None)
    assert settings.verification_integration == "disabled"
    assert settings.vexen_verification_schema == "legacy_roles"
    assert settings.vexmod_roles_schema == "legacy_roles"
