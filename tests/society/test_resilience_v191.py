from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_control_worker_recovers_from_transient_resource_failure():
    source = (ROOT / "app" / "bot" / "control_jobs.py").read_text(encoding="utf-8")
    assert "recoverable_error" in source
    assert "retry_in_seconds" in source
    assert "backoff = min(max(self.POLL_SECONDS, backoff * 2), 30)" in source
    assert "perdió temporalmente acceso a un recurso" in source
    assert 'return f"{type(exc).__name__}: {message}" if message else type(exc).__name__' in source


def test_discord_log_worker_recovers_instead_of_terminating():
    source = (ROOT / "app" / "society" / "logs.py").read_text(encoding="utf-8")
    assert "Sistema de logs Discord perdió temporalmente acceso a un recurso" in source
    assert "backoff = min(max(self.POLL_SECONDS, backoff * 2), 30)" in source
    assert "El sistema de logs Discord se detuvo inesperadamente" not in source


def test_application_requested_channels_are_created_by_bot():
    source = (ROOT / "app" / "bot" / "control_jobs.py").read_text(encoding="utf-8")
    assert "requested_channels JSONB" in source
    assert "def _requested_channels" in source
    assert "create_custom_channel" in source
    assert '"requested_channels_created": custom_channels' in source
    assert '{"TXT", "STAFF-TXT", "VOICE", "STAFF-VOICE"}' in source
