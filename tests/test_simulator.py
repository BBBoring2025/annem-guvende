"""Sensor simulator testleri."""

from datetime import datetime

import pytest

from src.database import get_db, init_db
from src.simulator.sensor_simulator import SensorSimulator


@pytest.fixture
def sim_db(tmp_path):
    """Simulasyon testi icin gecici DB."""
    db_path = str(tmp_path / "sim_test.db")
    init_db(db_path)
    return db_path


def _count_events(db_path, date=None, channel=None):
    """DB'deki event sayisini dondur."""
    with get_db(db_path) as conn:
        query = "SELECT COUNT(*) as cnt FROM sensor_events WHERE 1=1"
        params = []
        if date:
            query += " AND timestamp >= ? AND timestamp < ?"
            params.extend([f"{date}T00:00:00", f"{date}T23:59:59"])
        if channel:
            query += " AND channel = ?"
            params.append(channel)
        row = conn.execute(query, params).fetchone()
    return row["cnt"]


def _get_channels(db_path, date):
    """Belirli tarihteki benzersiz kanallari dondur."""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT channel FROM sensor_events "
            "WHERE timestamp >= ? AND timestamp < ?",
            (f"{date}T00:00:00", f"{date}T23:59:59"),
        ).fetchall()
    return {r["channel"] for r in rows}


# --- Normal gun testleri ---

def test_normal_day_event_count(sim_db):
    """Normal gun en az 30 event uretmeli."""
    sim = SensorSimulator(sim_db, seed=42)
    count = sim.generate_normal_day("2025-02-01")

    assert count >= 30
    assert _count_events(sim_db, "2025-02-01") == count


def test_normal_day_all_channels(sim_db):
    """Normal gun 4 kanalin hepsinde event olmali."""
    sim = SensorSimulator(sim_db, seed=42)
    sim.generate_normal_day("2025-02-01")

    channels = _get_channels(sim_db, "2025-02-01")
    assert channels == {"presence", "fridge", "bathroom", "door"}


def test_normal_day_timestamps_in_date(sim_db):
    """Tum eventler belirtilen tarihte olmali."""
    sim = SensorSimulator(sim_db, seed=42)
    sim.generate_normal_day("2025-03-15")

    with get_db(sim_db) as conn:
        rows = conn.execute("SELECT timestamp FROM sensor_events").fetchall()

    for row in rows:
        assert row["timestamp"].startswith("2025-03-15")


def test_normal_day_awake_window(sim_db):
    """Eventler 07:00-22:00 arasinda olmali."""
    sim = SensorSimulator(sim_db, seed=42)
    sim.generate_normal_day("2025-02-01")

    with get_db(sim_db) as conn:
        rows = conn.execute("SELECT timestamp FROM sensor_events").fetchall()

    for row in rows:
        dt = datetime.fromisoformat(row["timestamp"])
        assert 7 <= dt.hour <= 21, f"Event saat disinda: {row['timestamp']}"


# --- Anomali testleri ---

def test_anomaly_low_activity(sim_db):
    """low_activity: normal gune gore cok az event."""
    sim = SensorSimulator(sim_db, seed=42)
    normal_count = sim.generate_normal_day("2025-02-01")
    anomaly_count = sim.generate_anomaly_day("2025-02-02", "low_activity")

    assert anomaly_count < normal_count * 0.3  # %30'dan az


def test_anomaly_no_fridge(sim_db):
    """no_fridge: hic fridge eventi olmamali."""
    sim = SensorSimulator(sim_db, seed=42)
    sim.generate_anomaly_day("2025-02-01", "no_fridge")

    assert _count_events(sim_db, "2025-02-01", channel="fridge") == 0
    # Diger kanallar olmali
    assert _count_events(sim_db, "2025-02-01", channel="presence") > 0


def test_anomaly_no_bathroom(sim_db):
    """no_bathroom: hic bathroom eventi olmamali."""
    sim = SensorSimulator(sim_db, seed=42)
    sim.generate_anomaly_day("2025-02-01", "no_bathroom")

    assert _count_events(sim_db, "2025-02-01", channel="bathroom") == 0
    assert _count_events(sim_db, "2025-02-01", channel="presence") > 0


def test_anomaly_late_wake(sim_db):
    """late_wake: 11:00 oncesi event olmamali."""
    sim = SensorSimulator(sim_db, seed=42)
    sim.generate_anomaly_day("2025-02-01", "late_wake")

    with get_db(sim_db) as conn:
        rows = conn.execute("SELECT timestamp FROM sensor_events").fetchall()

    for row in rows:
        dt = datetime.fromisoformat(row["timestamp"])
        assert dt.hour >= 11, f"11:00 oncesi event: {row['timestamp']}"

    # Saat 11 sonrasi eventler olmali
    assert len(rows) > 0


def test_invalid_anomaly_type_raises(sim_db):
    """Gecersiz anomaly_type ValueError firlatmali."""
    sim = SensorSimulator(sim_db, seed=42)
    with pytest.raises(ValueError, match="Gecersiz anomaly_type"):
        sim.generate_anomaly_day("2025-02-01", "unknown_type")


# --- Pilot simulasyon testleri ---

def test_pilot_simulation_21_days(sim_db):
    """21 gunluk simulasyon 21 farkli gune event uretmeli."""
    sim = SensorSimulator(sim_db, seed=42)
    result = sim.run_pilot_simulation("2025-01-01", days=21)

    assert len(result["dates"]) == 21
    assert result["total_events"] > 0
    assert result["anomaly_date"] == "2025-01-18"  # Gun 18 (0-indexed 17)
    assert result["anomaly_type"] == "low_activity"

    # Her gun event var mi?
    for date in result["dates"]:
        assert _count_events(sim_db, date) > 0


def test_reproducible_with_seed(sim_db):
    """Ayni seed ile ayni event sayisi uretilmeli."""
    sim1 = SensorSimulator(sim_db, seed=123)
    count1 = sim1.generate_normal_day("2025-02-01")

    # Ikinci DB
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        db2 = os.path.join(tmp, "test2.db")
        init_db(db2)
        sim2 = SensorSimulator(db2, seed=123)
        count2 = sim2.generate_normal_day("2025-02-01")

    assert count1 == count2
