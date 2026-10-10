"""Over-subscribing worker slots must be noisy, not silent.

An explicit OCEANEYE_MAX_WORKERS always wins over the auto policy, but asking for more workers than
the machine's memory supports is what killed an earlier demo mid-run. The operator gets told.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main.factory import create_app
from app.shared.hardware import Hardware, recommend_worker_slots


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        _env_file=None, environment="test", database_url="sqlite://", evidence_dir=tmp_path / "e",
        escalation_monitor_enabled=False, weather_provider="mock", beaches_provider="mock",
        upload_dir=tmp_path / "u", jobs_dir=tmp_path / "j", logs_dir=tmp_path / "l",
    )
    base.update(over)
    return Settings(**base)


def test_asking_for_more_workers_than_the_machine_holds_is_logged(tmp_path, clock, launcher, caplog):
    app = create_app(_settings(tmp_path, max_workers=99), clock, launcher)
    with caplog.at_level(logging.WARNING, logger="app.main.container"), TestClient(app):
        pass
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("OCEANEYE_MAX_WORKERS=99" in m for m in warnings), warnings
    assert any("Insufficient memory" in m for m in warnings), "the warning should name the symptom"


def test_a_sane_worker_count_says_nothing(tmp_path, clock, launcher, caplog):
    app = create_app(_settings(tmp_path, max_workers=1), clock, launcher)
    with caplog.at_level(logging.WARNING, logger="app.main.container"), TestClient(app):
        pass
    assert not [r for r in caplog.records if "OCEANEYE_MAX_WORKERS" in r.getMessage()]


def test_auto_never_exceeds_its_own_recommendation(tmp_path, clock, launcher, caplog):
    """max_workers=0 resolves through the policy, so it can never warn about itself."""
    settings = _settings(tmp_path, max_workers=0)
    assert settings.max_workers >= 1
    app = create_app(settings, clock, launcher)
    with caplog.at_level(logging.WARNING, logger="app.main.container"), TestClient(app):
        pass
    assert not [r for r in caplog.records if "OCEANEYE_MAX_WORKERS" in r.getMessage()]


@pytest.mark.parametrize("hw,expected_max", [
    (Hardware(8, 16.0, 4.0, "RTX 2050"), 2),   # the machine this was built on
    (Hardware(4, 8.0, None, None), 1),
])
def test_the_recommendation_is_what_the_warning_compares_against(hw, expected_max):
    assert recommend_worker_slots(hw) == expected_max
