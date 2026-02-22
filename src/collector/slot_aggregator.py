"""15 dakikalik slot ozetleme - APScheduler ile periyodik calisir."""

import logging
from datetime import datetime, timedelta

from src.database import get_db

logger = logging.getLogger("annem_guvende.collector")


def get_slot(dt: datetime) -> int:
    """15dk slot numarasi (0-95).

    Ornek: 00:00 -> 0, 06:00 -> 24, 12:00 -> 48, 23:45 -> 95
    """
    return dt.hour * 4 + dt.minute // 15


def get_slot_time_range(dt: datetime) -> tuple[str, str]:
    """Verilen zaman icin slot baslangic ve bitis ISO zaman damgalari.

    Ornek: 10:37 -> ("2025-02-11T10:30:00", "2025-02-11T10:45:00")
    """
    slot_start_minute = (dt.minute // 15) * 15
    start = dt.replace(minute=slot_start_minute, second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    return start.isoformat(), end.isoformat()


def aggregate_current_slot(
    db_path: str,
    channels: list[str] | None = None,
    now: datetime | None = None,
) -> None:
    """Son 15 dakikadaki eventleri ozetle ve slot_summary'ye upsert et.

    APScheduler tarafindan her 15 dakikada cagirilir.
    now parametresi test edilebilirlik icin (default: datetime.now()).
    """
    if now is None:
        now = datetime.now()

    date_str = now.strftime("%Y-%m-%d")
    slot = get_slot(now)
    slot_start, slot_end = get_slot_time_range(now)

    with get_db(db_path) as conn:
        # Her kanal icin event say
        rows = conn.execute(
            "SELECT channel, COUNT(*) as cnt "
            "FROM sensor_events "
            "WHERE timestamp >= ? AND timestamp < ? "
            "GROUP BY channel",
            (slot_start, slot_end),
        ).fetchall()

        channel_counts = {row["channel"]: row["cnt"] for row in rows}

        # Tum kanallari isle (eventli + bos)
        all_channels = set(channels or []) | set(channel_counts.keys())
        for ch in all_channels:
            count = channel_counts.get(ch, 0)
            active = 1 if count > 0 else 0
            conn.execute(
                "INSERT INTO slot_summary (date, slot, channel, active, event_count) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (date, slot, channel) DO UPDATE SET "
                "active = excluded.active, event_count = excluded.event_count",
                (date_str, slot, ch, active, count),
            )
        conn.commit()

    if channel_counts:
        logger.info("Slot ozeti guncellendi: %s slot=%d, %d kanal", date_str, slot, len(channel_counts))


def fill_missing_slots(db_path: str, date_str: str, channels: list[str]) -> None:
    """Verilen gundeki bos slotlari active=0, event_count=0 olarak doldur.

    Her gun 00:05'te onceki gun icin cagirilir.
    INSERT OR IGNORE: mevcut satirlar korunur.
    """
    with get_db(db_path) as conn:
        for slot in range(96):
            for ch in channels:
                conn.execute(
                    "INSERT OR IGNORE INTO slot_summary "
                    "(date, slot, channel, active, event_count) "
                    "VALUES (?, ?, ?, 0, 0)",
                    (date_str, slot, ch),
                )
        conn.commit()

    logger.info("Eksik slotlar dolduruldu: %s, %d kanal", date_str, len(channels))
