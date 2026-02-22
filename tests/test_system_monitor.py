"""Sistem monitoru testleri."""

from collections import namedtuple
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.database import get_db, init_db
from src.heartbeat.system_monitor import (
    SystemMetrics,
    collect_system_metrics,
    get_cpu_percent,
    get_cpu_temp,
    get_db_size_mb,
    get_disk_percent,
    get_last_event_age_minutes,
    get_memory_percent,
    get_today_event_count,
)

# --- psutil mock testleri ---

@patch("src.heartbeat.system_monitor.psutil")
def test_get_cpu_percent(mock_psutil):
    """cpu_percent float dondurur."""
    mock_psutil.cpu_percent.return_value = 42.5
    result = get_cpu_percent()
    assert result == 42.5
    mock_psutil.cpu_percent.assert_called_once_with(interval=0)


@patch("src.heartbeat.system_monitor.psutil")
def test_get_memory_percent(mock_psutil):
    """memory_percent float dondurur."""
    mock_mem = MagicMock()
    mock_mem.percent = 67.3
    mock_psutil.virtual_memory.return_value = mock_mem
    result = get_memory_percent()
    assert result == 67.3


@patch("src.heartbeat.system_monitor.psutil")
def test_get_disk_percent(mock_psutil):
    """disk_percent float dondurur."""
    mock_disk = MagicMock()
    mock_disk.percent = 55.0
    mock_psutil.disk_usage.return_value = mock_disk
    result = get_disk_percent()
    assert result == 55.0
    mock_psutil.disk_usage.assert_called_once_with("/")


@patch("src.heartbeat.system_monitor.psutil")
def test_get_cpu_temp_on_pi(mock_psutil):
    """Pi'de cpu_thermal key'i ile sicaklik dondurur."""
    STemp = namedtuple("STemp", ["label", "current", "high", "critical"])
    mock_psutil.sensors_temperatures.return_value = {
        "cpu_thermal": [STemp(label="", current=55.0, high=85.0, critical=100.0)],
    }
    result = get_cpu_temp()
    assert result == 55.0


@patch("src.heartbeat.system_monitor.psutil")
def test_get_cpu_temp_not_available(mock_psutil):
    """Pi olmayan platformda None dondurur."""
    # sensors_temperatures bos dict dondururse
    mock_psutil.sensors_temperatures.return_value = {}
    result = get_cpu_temp()
    assert result is None


@patch("src.heartbeat.system_monitor.psutil")
def test_get_cpu_temp_attribute_error(mock_psutil):
    """sensors_temperatures yoksa (macOS) None dondurur."""
    mock_psutil.sensors_temperatures.side_effect = AttributeError
    result = get_cpu_temp()
    assert result is None


# --- DB metrik testleri ---

@pytest.fixture
def monitor_db(tmp_path):
    """Sistem monitoru testleri icin hazir DB."""
    db_path = str(tmp_path / "monitor_test.db")
    init_db(db_path)
    return db_path


def test_get_db_size_mb(monitor_db):
    """DB boyutu kucuk pozitif float."""
    result = get_db_size_mb(monitor_db)
    assert isinstance(result, float)
    assert result > 0.0


def test_get_db_size_mb_no_file():
    """Dosya yoksa 0.0 dondurur."""
    result = get_db_size_mb("/tmp/nonexistent_db_12345.db")
    assert result == 0.0


def test_get_last_event_age_no_events(monitor_db):
    """Event yoksa None dondurur."""
    now = datetime(2025, 3, 1, 14, 0, 0)
    result = get_last_event_age_minutes(monitor_db, now=now)
    assert result is None


def test_get_last_event_age_with_event(monitor_db):
    """Event varsa dogru dakika hesaplar."""
    now = datetime(2025, 3, 1, 14, 30, 0)

    # 30 dk once event ekle
    with get_db(monitor_db) as conn:
        conn.execute(
            """INSERT INTO sensor_events (timestamp, sensor_id, channel, value)
               VALUES (?, ?, ?, ?)""",
            ("2025-03-01T14:00:00", "test_sensor", "presence", "on"),
        )
        conn.commit()

    result = get_last_event_age_minutes(monitor_db, now=now)
    assert result is not None
    assert abs(result - 30.0) < 1.0  # ~30 dakika


def test_get_today_event_count(monitor_db):
    """Bugunun event sayisi dogru."""
    now = datetime(2025, 3, 1, 14, 0, 0)

    with get_db(monitor_db) as conn:
        # Bugun: 3 event
        for i in range(3):
            conn.execute(
                """INSERT INTO sensor_events (timestamp, sensor_id, channel, value)
                   VALUES (?, ?, ?, ?)""",
                (f"2025-03-01T{10 + i}:00:00", f"sensor_{i}", "presence", "on"),
            )
        # Dun: 2 event (sayilmamali)
        for i in range(2):
            conn.execute(
                """INSERT INTO sensor_events (timestamp, sensor_id, channel, value)
                   VALUES (?, ?, ?, ?)""",
                (f"2025-02-28T{10 + i}:00:00", f"sensor_{i}", "presence", "on"),
            )
        conn.commit()

    result = get_today_event_count(monitor_db, now=now)
    assert result == 3


def test_get_today_event_count_no_events(monitor_db):
    """Event yoksa 0 dondurur."""
    now = datetime(2025, 3, 1, 14, 0, 0)
    result = get_today_event_count(monitor_db, now=now)
    assert result == 0


@patch("src.heartbeat.system_monitor.psutil")
def test_collect_system_metrics(mock_psutil, monitor_db):
    """collect_system_metrics tum alanlari doldurur."""
    # psutil mock'lari
    mock_psutil.cpu_percent.return_value = 25.0
    mock_mem = MagicMock()
    mock_mem.percent = 60.0
    mock_psutil.virtual_memory.return_value = mock_mem
    mock_disk = MagicMock()
    mock_disk.percent = 45.0
    mock_psutil.disk_usage.return_value = mock_disk
    mock_psutil.sensors_temperatures.return_value = {}
    mock_psutil.boot_time.return_value = 1000.0

    now = datetime(2025, 3, 1, 14, 0, 0)

    with patch("src.heartbeat.system_monitor.time") as mock_time:
        mock_time.time.return_value = 2000.0
        result = collect_system_metrics(monitor_db, now=now)

    assert isinstance(result, SystemMetrics)
    assert result.cpu_percent == 25.0
    assert result.memory_percent == 60.0
    assert result.disk_percent == 45.0
    assert result.cpu_temp is None  # mock bos dict
    assert result.db_size_mb > 0.0
    assert result.today_event_count == 0
    assert result.last_event_age_minutes is None
    assert result.uptime_seconds == 1000.0
