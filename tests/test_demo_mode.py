"""Demo mode testleri."""

from src.database import init_db
from src.simulator.sensor_simulator import SensorSimulator


def test_demo_runs_21_days(tmp_path):
    """run_demo 21 gun uretmeli."""
    db_path = str(tmp_path / "demo.db")
    init_db(db_path)
    sim = SensorSimulator(db_path, seed=42)

    result = sim.run_demo(day_duration_seconds=0)

    assert len(result["dates"]) == 21
    assert result["total_events"] > 0


def test_demo_callback_called(tmp_path):
    """Callback her gun cagirilmali (21 kez)."""
    db_path = str(tmp_path / "demo.db")
    init_db(db_path)
    sim = SensorSimulator(db_path, seed=42)
    calls = []

    def track(day_num, date, event_count, is_anomaly):
        calls.append((day_num, date, event_count, is_anomaly))

    sim.run_demo(day_duration_seconds=0, callback=track)

    assert len(calls) == 21
    assert calls[0][0] == 1
    assert calls[-1][0] == 21


def test_demo_has_anomaly(tmp_path):
    """Demo'da anomali gunu olmali."""
    db_path = str(tmp_path / "demo.db")
    init_db(db_path)
    sim = SensorSimulator(db_path, seed=42)

    result = sim.run_demo(day_duration_seconds=0)

    assert result["anomaly_date"] is not None
    assert result["anomaly_type"] == "low_activity"


def test_demo_callback_reports_anomaly(tmp_path):
    """Callback'te anomali gunu is_anomaly=True olmali (gun 18)."""
    db_path = str(tmp_path / "demo.db")
    init_db(db_path)
    sim = SensorSimulator(db_path, seed=42)
    anomaly_days = []

    def track(day_num, date, event_count, is_anomaly):
        if is_anomaly:
            anomaly_days.append(day_num)

    sim.run_demo(day_duration_seconds=0, callback=track)

    assert len(anomaly_days) == 1
    assert anomaly_days[0] == 18
