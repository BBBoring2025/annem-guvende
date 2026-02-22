"""Veritabani katmani testleri - tablo olusturma, insert/select, migration."""

from src.database import get_db, init_db


def test_init_db_creates_tables(initialized_db):
    """init_db() sonrasi 6 tablo mevcut olmali."""
    expected_tables = {
        "schema_version",
        "sensor_events",
        "slot_summary",
        "daily_scores",
        "model_state",
        "system_state",
    }
    with get_db(initialized_db) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        actual_tables = {row["name"] for row in cursor.fetchall()}

    assert expected_tables.issubset(actual_tables), (
        f"Eksik tablolar: {expected_tables - actual_tables}"
    )


def test_init_db_creates_indexes(initialized_db):
    """init_db() sonrasi 2 index mevcut olmali."""
    expected_indexes = {"idx_events_ts", "idx_events_channel"}
    with get_db(initialized_db) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
        actual_indexes = {row["name"] for row in cursor.fetchall()}

    assert expected_indexes.issubset(actual_indexes), (
        f"Eksik indexler: {expected_indexes - actual_indexes}"
    )


def test_init_db_idempotent(db_path):
    """init_db() iki kez cagrilinca hata vermemeli."""
    init_db(db_path)
    init_db(db_path)

    with get_db(db_path) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]

    # Migration sayisi MIGRATIONS listesindeki toplam kadar olmali
    from src.database import MIGRATIONS
    assert count == len(MIGRATIONS)


def test_insert_sensor_event(initialized_db):
    """sensor_events tablosuna INSERT + SELECT roundtrip."""
    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-11T10:30:00", "mutfak_motion", "presence", "state_change", "on"),
        )
        conn.commit()

        cursor = conn.execute("SELECT * FROM sensor_events WHERE sensor_id = ?", ("mutfak_motion",))
        row = cursor.fetchone()

    assert row is not None
    assert row["timestamp"] == "2025-02-11T10:30:00"
    assert row["sensor_id"] == "mutfak_motion"
    assert row["channel"] == "presence"
    assert row["value"] == "on"


def test_insert_slot_summary(initialized_db):
    """slot_summary tablosuna composite PK ile INSERT + SELECT."""
    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO slot_summary (date, slot, channel, active, event_count) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-11", 42, "presence", 1, 5),
        )
        conn.commit()

        cursor = conn.execute(
            "SELECT * FROM slot_summary WHERE date = ? AND slot = ? AND channel = ?",
            ("2025-02-11", 42, "presence"),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["active"] == 1
    assert row["event_count"] == 5


def test_insert_daily_scores(initialized_db):
    """daily_scores tablosuna INSERT + SELECT."""
    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO daily_scores (date, train_days, nll_total, composite_z, alert_level) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-11", 10, 45.3, 1.5, 0),
        )
        conn.commit()

        cursor = conn.execute("SELECT * FROM daily_scores WHERE date = ?", ("2025-02-11",))
        row = cursor.fetchone()

    assert row is not None
    assert row["train_days"] == 10
    assert row["nll_total"] == 45.3
    assert row["composite_z"] == 1.5
    assert row["alert_level"] == 0


def test_insert_model_state(initialized_db):
    """model_state tablosuna composite PK ile INSERT + SELECT."""
    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO model_state (slot, channel, alpha, beta) VALUES (?, ?, ?, ?)",
            (24, "presence", 5.0, 3.0),
        )
        conn.commit()

        cursor = conn.execute(
            "SELECT * FROM model_state WHERE slot = ? AND channel = ?",
            (24, "presence"),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["alpha"] == 5.0
    assert row["beta"] == 3.0


def test_schema_version(initialized_db):
    """schema_version tablosunda tum migration versiyonlari kayitli olmali."""
    from src.database import MIGRATIONS

    with get_db(initialized_db) as conn:
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version")
        rows = cursor.fetchall()

    assert len(rows) == len(MIGRATIONS)
    expected_versions = [v for v, _ in MIGRATIONS]
    actual_versions = [r["version"] for r in rows]
    assert actual_versions == expected_versions
