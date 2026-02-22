"""Slot aggregator testleri - slot hesaplama, ozetleme, bos slot doldurma."""

from datetime import datetime, timedelta

from src.collector.slot_aggregator import (
    aggregate_current_slot,
    fill_missing_slots,
    get_slot,
    get_slot_time_range,
)
from src.database import get_db

# --- get_slot testleri ---

def test_get_slot_midnight():
    """00:00 -> slot 0."""
    assert get_slot(datetime(2025, 2, 11, 0, 0)) == 0


def test_get_slot_morning():
    """06:00 -> slot 24."""
    assert get_slot(datetime(2025, 2, 11, 6, 0)) == 24


def test_get_slot_noon():
    """12:00 -> slot 48."""
    assert get_slot(datetime(2025, 2, 11, 12, 0)) == 48


def test_get_slot_last():
    """23:45 -> slot 95 (son slot)."""
    assert get_slot(datetime(2025, 2, 11, 23, 45)) == 95


def test_get_slot_mid_slot():
    """10:37 -> slot 42 (10:30-10:45 dilimi)."""
    assert get_slot(datetime(2025, 2, 11, 10, 37)) == 42


# --- get_slot_time_range testleri ---

def test_get_slot_time_range_aligned():
    """Slot baslangicina hizali zaman -> dogru aralik."""
    start, end = get_slot_time_range(datetime(2025, 2, 11, 10, 30, 0))
    assert start == "2025-02-11T10:30:00"
    assert end == "2025-02-11T10:45:00"


def test_get_slot_time_range_mid():
    """Slot ortasindaki zaman -> ayni aralik."""
    start, end = get_slot_time_range(datetime(2025, 2, 11, 10, 37, 25))
    assert start == "2025-02-11T10:30:00"
    assert end == "2025-02-11T10:45:00"


# --- aggregate_current_slot testleri ---

def test_aggregate_single_channel(initialized_db):
    """Tek kanalda 3 event -> active=1, event_count=3."""
    now = datetime(2025, 2, 11, 10, 35, 0)

    # 10:30-10:45 arasinda 3 event ekle
    with get_db(initialized_db) as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"2025-02-11T10:3{i}:00", "mutfak_motion", "presence", "state_change", "on"),
            )
        conn.commit()

    aggregate_current_slot(initialized_db, channels=["presence"], now=now)

    with get_db(initialized_db) as conn:
        row = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=? AND channel=?",
            ("2025-02-11", 42, "presence"),
        ).fetchone()

    assert row is not None
    assert row["active"] == 1
    assert row["event_count"] == 3


def test_aggregate_multiple_channels(initialized_db):
    """Birden fazla kanalda event -> ayri satirlar."""
    now = datetime(2025, 2, 11, 10, 35, 0)

    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-11T10:32:00", "mutfak_motion", "presence", "state_change", "on"),
        )
        conn.execute(
            "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-11T10:33:00", "buzdolabi_kapi", "fridge", "state_change", "open"),
        )
        conn.commit()

    aggregate_current_slot(initialized_db, channels=["presence", "fridge"], now=now)

    with get_db(initialized_db) as conn:
        rows = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=?",
            ("2025-02-11", 42),
        ).fetchall()

    assert len(rows) == 2
    channels = {r["channel"] for r in rows}
    assert channels == {"presence", "fridge"}


def test_aggregate_no_events_creates_empty(initialized_db):
    """Event yok ama kanal belirtilmis -> active=0, event_count=0."""
    now = datetime(2025, 2, 11, 10, 35, 0)

    aggregate_current_slot(initialized_db, channels=["presence"], now=now)

    with get_db(initialized_db) as conn:
        row = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=? AND channel=?",
            ("2025-02-11", 42, "presence"),
        ).fetchone()

    assert row is not None
    assert row["active"] == 0
    assert row["event_count"] == 0


def test_aggregate_idempotent(initialized_db):
    """Ayni slot icin 2 kez cagrilinca sonuc ayni (upsert)."""
    now = datetime(2025, 2, 11, 10, 35, 0)

    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-11T10:32:00", "mutfak_motion", "presence", "state_change", "on"),
        )
        conn.commit()

    aggregate_current_slot(initialized_db, channels=["presence"], now=now)
    aggregate_current_slot(initialized_db, channels=["presence"], now=now)

    with get_db(initialized_db) as conn:
        rows = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=? AND channel=?",
            ("2025-02-11", 42, "presence"),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["event_count"] == 1


# --- fill_missing_slots testleri ---

def test_fill_missing_creates_all_slots(initialized_db):
    """4 kanal x 96 slot = 384 satir olusturulmali."""
    channels = ["presence", "fridge", "bathroom", "door"]
    fill_missing_slots(initialized_db, "2025-02-11", channels)

    with get_db(initialized_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM slot_summary WHERE date=?", ("2025-02-11",)
        ).fetchone()[0]

    assert count == 384  # 96 * 4


def test_fill_missing_preserves_existing(initialized_db):
    """Mevcut satirlar korunur (INSERT OR IGNORE)."""
    # Once gercek veri ekle
    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO slot_summary (date, slot, channel, active, event_count) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-11", 42, "presence", 1, 5),
        )
        conn.commit()

    # Bos slotlari doldur
    fill_missing_slots(initialized_db, "2025-02-11", ["presence"])

    # Mevcut satir korunmus mu?
    with get_db(initialized_db) as conn:
        row = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=? AND channel=?",
            ("2025-02-11", 42, "presence"),
        ).fetchone()

    assert row["active"] == 1
    assert row["event_count"] == 5  # Uzerine yazilmamis


# --- gece yarisi gecisi testi ---

def test_midnight_transition(initialized_db):
    """23:50 ve 00:05 eventleri farkli gun ve slotlara dusmeli."""
    # 23:50 -> slot 95, tarih 2025-02-11
    now_before = datetime(2025, 2, 11, 23, 50, 0)
    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-11T23:50:00", "mutfak_motion", "presence", "state_change", "on"),
        )
        conn.commit()
    aggregate_current_slot(initialized_db, channels=["presence"], now=now_before)

    # 00:05 -> slot 0, tarih 2025-02-12
    now_after = datetime(2025, 2, 12, 0, 5, 0)
    with get_db(initialized_db) as conn:
        conn.execute(
            "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2025-02-12T00:05:00", "mutfak_motion", "presence", "state_change", "on"),
        )
        conn.commit()
    aggregate_current_slot(initialized_db, channels=["presence"], now=now_after)

    with get_db(initialized_db) as conn:
        row1 = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=?",
            ("2025-02-11", 95),
        ).fetchone()
        row2 = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=?",
            ("2025-02-12", 0),
        ).fetchone()

    assert row1 is not None
    assert row1["active"] == 1
    assert row2 is not None
    assert row2["active"] == 1


# --- slot boundary testleri (Bug Fix 1) ---

def test_slot_boundary_previous_slot(initialized_db):
    """Job slot basinda calistiginda 1dk geri alininca onceki slot ozetlenir.

    Senaryo: 10:05-10:14 arasi eventler var, now=10:14 (adjusted) ile aggregate
    cagirilinca slot 40 (10:00-10:15) active=1 olmali.
    """
    # 10:00-10:15 arasinda 3 event ekle
    with get_db(initialized_db) as conn:
        for minute in [5, 8, 14]:
            conn.execute(
                "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"2025-02-11T10:{minute:02d}:00", "mutfak_motion", "presence", "state_change", "on"),
            )
        conn.commit()

    # Job 10:15'te calisir → adjusted_now = 10:15 - 1dk = 10:14
    job_fire_time = datetime(2025, 2, 11, 10, 15, 0)
    adjusted_now = job_fire_time - timedelta(minutes=1)
    aggregate_current_slot(initialized_db, channels=["presence"], now=adjusted_now)

    with get_db(initialized_db) as conn:
        row = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=? AND channel=?",
            ("2025-02-11", 40, "presence"),
        ).fetchone()

    assert row is not None
    assert row["active"] == 1
    assert row["event_count"] == 3


def test_slot_boundary_exact_start_sees_empty(initialized_db):
    """Duzeltme ONCESI davranis: now=10:15 ile cagrilinca 10:15-10:30 slotu
    sorgulanir, henuz event yok → active=0.

    Bu test zamanlama hatasinin neden olustuguniu belgeler.
    """
    # 10:00-10:15 arasinda eventler var (onceki slot)
    with get_db(initialized_db) as conn:
        for minute in [5, 8, 14]:
            conn.execute(
                "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"2025-02-11T10:{minute:02d}:00", "mutfak_motion", "presence", "state_change", "on"),
            )
        conn.commit()

    # Duzeltme olmadan: now=10:15 → slot 41 (10:15-10:30) sorgulanir, bos!
    now_exact = datetime(2025, 2, 11, 10, 15, 0)
    aggregate_current_slot(initialized_db, channels=["presence"], now=now_exact)

    with get_db(initialized_db) as conn:
        row = conn.execute(
            "SELECT * FROM slot_summary WHERE date=? AND slot=? AND channel=?",
            ("2025-02-11", 41, "presence"),
        ).fetchone()

    assert row is not None
    assert row["active"] == 0  # Bos slot - eventler onceki slotta
    assert row["event_count"] == 0
