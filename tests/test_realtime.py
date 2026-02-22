"""Gercek zamanli sessizlik kontrol testleri."""

from datetime import datetime

import pytest

from src.config import AppConfig
from src.database import get_db, init_db
from src.detector.realtime_checks import (
    check_extended_silence,
    check_morning_vital_sign,
    run_realtime_checks,
)


def _insert_sensor_event(db_path: str, timestamp_str: str,
                         sensor_id: str = "mutfak_motion",
                         channel: str = "presence"):
    """Test icin sensor event ekle."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO sensor_events "
            "(timestamp, sensor_id, channel, event_type, value) "
            "VALUES (?, ?, ?, 'state_change', 'on')",
            (timestamp_str, sensor_id, channel),
        )
        conn.commit()


def _default_config():
    return AppConfig(
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7, "morning_check_hour": 11, "silence_threshold_hours": 3},
        model={"awake_start_hour": 6, "awake_end_hour": 23},
    )


@pytest.fixture
def realtime_db(tmp_path):
    """Realtime testleri icin hazir DB."""
    db_path = str(tmp_path / "realtime_test.db")
    init_db(db_path)
    return db_path


# --- Sabah Vital Sign Testleri ---

def test_morning_silence_no_events(realtime_db):
    """Saat 11:30, hic event yok -> morning_silence, alert_level=2."""
    now = datetime(2025, 3, 1, 11, 30)
    result = check_morning_vital_sign(realtime_db, _default_config(), now=now)

    assert result is not None
    assert result.alert_type == "morning_silence"
    assert result.alert_level == 2


def test_morning_silence_before_11am(realtime_db):
    """Saat 10:30 (11'den once) -> None (henuz kontrol zamani degil)."""
    now = datetime(2025, 3, 1, 10, 30)
    result = check_morning_vital_sign(realtime_db, _default_config(), now=now)

    assert result is None


def test_morning_has_events(realtime_db):
    """Sabah event var -> None (alarm yok)."""
    _insert_sensor_event(realtime_db, "2025-03-01T08:15:00")
    now = datetime(2025, 3, 1, 12, 0)
    result = check_morning_vital_sign(realtime_db, _default_config(), now=now)

    assert result is None


# --- Uzun Sessizlik Testleri ---

def test_extended_silence_3_hours(realtime_db):
    """Son event 3.5 saat once -> extended_silence, alert_level=1."""
    _insert_sensor_event(realtime_db, "2025-03-01T09:00:00")
    now = datetime(2025, 3, 1, 12, 30)
    result = check_extended_silence(realtime_db, _default_config(), now=now)

    assert result is not None
    assert result.alert_type == "extended_silence"
    assert result.alert_level == 1


def test_extended_silence_within_threshold(realtime_db):
    """Son event 2.5 saat once -> None (esik altinda)."""
    _insert_sensor_event(realtime_db, "2025-03-01T10:00:00")
    now = datetime(2025, 3, 1, 12, 30)
    result = check_extended_silence(realtime_db, _default_config(), now=now)

    assert result is None


def test_extended_silence_outside_awake_window(realtime_db):
    """Gece saati (02:00) -> None (awake window disinda)."""
    _insert_sensor_event(realtime_db, "2025-03-01T22:00:00")
    now = datetime(2025, 3, 2, 2, 0)
    result = check_extended_silence(realtime_db, _default_config(), now=now)

    assert result is None


# --- Birlesik Kontrol Testi ---

def test_run_realtime_checks_morning_silence(realtime_db):
    """Saat 12:00, hic event yok -> en az 1 alert."""
    now = datetime(2025, 3, 1, 12, 0)
    alerts = run_realtime_checks(realtime_db, _default_config(), now=now)

    assert len(alerts) >= 1
    alert_types = [a.alert_type for a in alerts]
    assert "morning_silence" in alert_types
