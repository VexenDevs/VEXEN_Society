from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_verification_integration_uses_current_vexen_contract():
    source = (ROOT / "app" / "integrations" / "verification.py").read_text(
        encoding="utf-8"
    )
    assert "settings.vexen_verification_schema" in source
    assert "onboarding_role_id" in source
    assert "verified_role_id" in source
    assert 'role_transfers' in source
    assert "official_role_key" not in source
    assert "intent_role_id" not in source


def test_society_lifecycle_registers_and_removes_mapping_and_onboarding_option():
    source = (ROOT / "app" / "society" / "spaces.py").read_text(encoding="utf-8")
    assert "verification.register_transfer" in source
    assert "upsert_associate_option" in source
    assert "remove_associate_option" in source
    assert "verification.remove_transfer" in source


def test_v110_space_service_requires_confirmed_onboarding_and_uses_db_ids_for_order():
    client = (ROOT / "app" / "bot" / "client.py").read_text(encoding="utf-8")
    service = (ROOT / "app" / "society" / "space_service_v110.py").read_text(encoding="utf-8")
    assert "VexenSpaceService" in client
    assert 'ONBOARDING_SUCCESS_STATES = {"added", "updated", "already"}' in service
    assert "list_associates" in service
    assert 'row["category_id"]' in service
    assert "No se creó la Society porque su rol INT no quedó añadido" in service
