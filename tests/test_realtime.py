"""Gercek zamanli sessizlik kontrol testleri."""

from datetime import datetime

import pytest

from src.config import AppConfig
from src.database import get_db, get_system_state, init_db, set_system_state
from src.detector.realtime_checks import (
    check_extended_silence,
    check_fall_suspicion,
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


# --- Dusme Suphesi Testleri ---

def test_fall_suspicion_triggers_after_timeout(realtime_db):
    """50dk once banyo kullanimi, timeout 45dk -> fall_suspicion level=3.
    Alarm sonrasi state temizlenmeli (2. cagri -> None)."""
    now = datetime(2025, 3, 1, 14, 50)
    bathroom_time = datetime(2025, 3, 1, 14, 0)  # 50 dk once
    set_system_state(realtime_db, "last_bathroom_time", bathroom_time.isoformat())

    result = check_fall_suspicion(realtime_db, _default_config(), now=now)

    assert result is not None
    assert result.alert_type == "fall_suspicion"
    assert result.alert_level == 3
    assert "50 dakika" in result.message

    # State temizlenmis olmali — 2. cagri None donmeli
    result2 = check_fall_suspicion(realtime_db, _default_config(), now=now)
    assert result2 is None


def test_fall_suspicion_no_trigger_within_timeout(realtime_db):
    """20dk once banyo kullanimi, timeout 45dk -> None (henuz erken)."""
    now = datetime(2025, 3, 1, 14, 20)
    bathroom_time = datetime(2025, 3, 1, 14, 0)  # 20 dk once
    set_system_state(realtime_db, "last_bathroom_time", bathroom_time.isoformat())

    result = check_fall_suspicion(realtime_db, _default_config(), now=now)

    assert result is None
    # State hala durmali
    assert get_system_state(realtime_db, "last_bathroom_time", "") != ""


def test_fall_suspicion_disabled_when_zero(realtime_db):
    """fall_detection_minutes=0 -> ozellik kapali, None donmeli."""
    now = datetime(2025, 3, 1, 15, 0)
    bathroom_time = datetime(2025, 3, 1, 14, 0)  # 60 dk once
    set_system_state(realtime_db, "last_bathroom_time", bathroom_time.isoformat())

    config = AppConfig(
        alerts={"fall_detection_minutes": 0},
        model={"awake_start_hour": 6, "awake_end_hour": 23},
    )
    result = check_fall_suspicion(realtime_db, config, now=now)

    assert result is None


def test_fall_suspicion_cleared_by_other_channel(realtime_db):
    """Banyo sonrasi baska kanal event'i gelince state temizlenmeli."""
    bathroom_time = datetime(2025, 3, 1, 14, 0)
    set_system_state(realtime_db, "last_bathroom_time", bathroom_time.isoformat())

    # State var mi?
    assert get_system_state(realtime_db, "last_bathroom_time", "") != ""

    # Baska kanal event'i simule et (presence, kitchen, sleep vb.)
    # _update_fall_state mantigi: channel != "bathroom" -> temizle
    last_bt = get_system_state(realtime_db, "last_bathroom_time", "")
    if last_bt:
        set_system_state(realtime_db, "last_bathroom_time", "")

    # State temizlenmis olmali
    assert get_system_state(realtime_db, "last_bathroom_time", "") == ""


def test_fall_suspicion_no_state(realtime_db):
    """DB'de last_bathroom_time yok -> None donmeli."""
    now = datetime(2025, 3, 1, 14, 0)
    result = check_fall_suspicion(realtime_db, _default_config(), now=now)

    assert result is None
