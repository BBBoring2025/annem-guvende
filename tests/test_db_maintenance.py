"""FIX 5 Tests: Disk cleanup + DB maintenance.

- Eski eventler siliniyor
- Yeni eventler korunuyor
- Maintenance fonksiyonu hata atmiyor
- busy_timeout aktif
"""

from datetime import datetime, timedelta

import pytest

from src.database import (
    cleanup_old_events,
    get_db,
    init_db,
    run_db_maintenance,
)


@pytest.fixture
def maint_db(tmp_path):
    db_path = str(tmp_path / "maint_test.db")
    init_db(db_path)
    return db_path


def _insert_event(db_path, timestamp, sensor_id="test_sensor", channel="presence"):
    """Test icin sensor_events'e kayit ekle."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type) "
            "VALUES (?, ?, ?, 'state_change')",
            (timestamp, sensor_id, channel),
        )
        conn.commit()


def test_cleanup_old_events_deletes_old(maint_db):
    """retention_days gunden eski eventler silinmeli."""
    # 100 gun oncesi event
    old_ts = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%dT12:00:00")
    _insert_event(maint_db, old_ts)

    # Bugunun event'i
    new_ts = datetime.now().strftime("%Y-%m-%dT12:00:00")
    _insert_event(maint_db, new_ts)

    deleted = cleanup_old_events(maint_db, retention_days=90)

    assert deleted == 1, f"1 eski event silinmeliydi, {deleted} silindi"

    # Yeni event hala var mi?
    with get_db(maint_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sensor_events").fetchone()[0]
    assert count == 1, "Yeni event de silinmis!"


def test_cleanup_preserves_recent_events(maint_db):
    """Yeni eventler korunmali."""
    # 30 gun oncesi event (retention=90 icinde)
    recent_ts = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT12:00:00")
    _insert_event(maint_db, recent_ts)

    deleted = cleanup_old_events(maint_db, retention_days=90)

    assert deleted == 0, "Yeni event yanlislikla silinmis!"

    with get_db(maint_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sensor_events").fetchone()[0]
    assert count == 1


def test_cleanup_returns_zero_when_empty(maint_db):
    """Bos DB'de cleanup 0 dondurur."""
    deleted = cleanup_old_events(maint_db, retention_days=90)
    assert deleted == 0


def test_run_db_maintenance_no_error(maint_db):
    """run_db_maintenance hata atmamali."""
    # Biraz veri ekle
    _insert_event(maint_db, datetime.now().strftime("%Y-%m-%dT12:00:00"))

    # Hata atmamalI
    run_db_maintenance(maint_db)


def test_busy_timeout_is_set(maint_db):
    """get_db() busy_timeout=5000 set etmeli."""
    with get_db(maint_db) as conn:
        result = conn.execute("PRAGMA busy_timeout").fetchone()
    assert result[0] == 5000, f"busy_timeout={result[0]}, 5000 bekleniyor"
