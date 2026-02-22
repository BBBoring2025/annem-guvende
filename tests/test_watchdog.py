"""Watchdog saglik kontrolu testleri."""

from src.heartbeat.system_monitor import SystemMetrics
from src.heartbeat.watchdog import (
    check_cpu_temp,
    check_db_health,
    check_disk_usage,
    check_mqtt_status,
    check_ram_usage,
    format_watchdog_alert,
    run_health_checks,
)


def _normal_metrics(**overrides) -> SystemMetrics:
    """Normal degerlerle SystemMetrics olustur."""
    defaults = dict(
        cpu_percent=25.0,
        memory_percent=60.0,
        disk_percent=45.0,
        cpu_temp=55.0,
        db_size_mb=10.0,
        last_event_age_minutes=5.0,
        today_event_count=100,
        uptime_seconds=86400.0,
    )
    defaults.update(overrides)
    return SystemMetrics(**defaults)


# --- Bireysel check testleri ---

def test_cpu_temp_normal():
    """Normal sicaklik -> saglikli."""
    result = check_cpu_temp(_normal_metrics(cpu_temp=55.0))
    assert result.healthy is True


def test_cpu_temp_warning():
    """CPU > 80°C -> sagliksiz."""
    result = check_cpu_temp(_normal_metrics(cpu_temp=85.0))
    assert result.healthy is False
    assert "85.0" in result.message


def test_cpu_temp_none_ok():
    """Pi olmayan platform (None) -> saglikli."""
    result = check_cpu_temp(_normal_metrics(cpu_temp=None))
    assert result.healthy is True


def test_disk_warning():
    """Disk > %90 -> sagliksiz."""
    result = check_disk_usage(_normal_metrics(disk_percent=92.0))
    assert result.healthy is False


def test_disk_normal():
    """Disk normal -> saglikli."""
    result = check_disk_usage(_normal_metrics(disk_percent=50.0))
    assert result.healthy is True


def test_ram_warning():
    """RAM > %85 -> sagliksiz."""
    result = check_ram_usage(_normal_metrics(memory_percent=87.0))
    assert result.healthy is False


def test_ram_normal():
    """RAM normal -> saglikli."""
    result = check_ram_usage(_normal_metrics(memory_percent=60.0))
    assert result.healthy is True


def test_mqtt_disconnected():
    """MQTT kopuk -> sagliksiz."""
    result = check_mqtt_status(mqtt_connected=False, last_event_age_minutes=5.0)
    assert result.healthy is False
    assert "kopuk" in result.message


def test_mqtt_connected():
    """MQTT bagli -> saglikli."""
    result = check_mqtt_status(mqtt_connected=True, last_event_age_minutes=5.0)
    assert result.healthy is True


def test_db_health_warning():
    """DB > 500 MB -> sagliksiz."""
    result = check_db_health(db_size_mb=550.0)
    assert result.healthy is False


def test_db_health_normal():
    """DB normal -> saglikli."""
    result = check_db_health(db_size_mb=10.0)
    assert result.healthy is True


# --- run_health_checks testleri ---

def test_all_healthy():
    """Tum kontroller saglikli -> all_healthy=True."""
    metrics = _normal_metrics()
    status = run_health_checks(metrics, mqtt_connected=True)

    assert status.all_healthy is True
    assert len(status.warnings) == 0
    assert len(status.checks) == 5


def test_mixed_health():
    """Bazi sagliksiz -> warnings sadece onlari icerir."""
    metrics = _normal_metrics(disk_percent=95.0, memory_percent=90.0)
    status = run_health_checks(metrics, mqtt_connected=True)

    assert status.all_healthy is False
    assert len(status.warnings) == 2
    warning_names = {w.name for w in status.warnings}
    assert "disk" in warning_names
    assert "ram" in warning_names


# --- format_watchdog_alert testleri ---

def test_format_alert_all_healthy():
    """Tumnu saglikli -> None dondurur."""
    metrics = _normal_metrics()
    status = run_health_checks(metrics, mqtt_connected=True)

    result = format_watchdog_alert(status)
    assert result is None


def test_format_alert_with_warnings():
    """Uyari var -> Turkce mesaj iceriyor."""
    metrics = _normal_metrics(disk_percent=95.0, cpu_temp=85.0)
    status = run_health_checks(metrics, mqtt_connected=True)

    result = format_watchdog_alert(status)
    assert result is not None
    assert "Sağlık Uyarısı" in result
    assert "Disk" in result
    assert "CPU" in result


def test_format_alert_mqtt_disconnected_shows_internet_note():
    """MQTT kopuk uyarisinda internet kesintisi notu olmali."""
    metrics = _normal_metrics()
    status = run_health_checks(metrics, mqtt_connected=False)

    result = format_watchdog_alert(status)
    assert result is not None
    assert "internet" in result.lower()
    assert "kesinti" in result.lower()
