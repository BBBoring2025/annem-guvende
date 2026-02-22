"""SQLite veritabani baglantisi ve migration yonetimi."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger("annem_guvende")

# Migration tanimlari: (versiyon, sql)
# Her yeni sprint gerekirse buraya yeni migration ekler
MIGRATIONS = [
    (1, """
    -- Sema versiyonu 1: Temel tablolar

    CREATE TABLE IF NOT EXISTS sensor_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT NOT NULL,
        sensor_id   TEXT NOT NULL,
        channel     TEXT NOT NULL,
        event_type  TEXT NOT NULL DEFAULT 'state_change',
        value       TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_events_ts ON sensor_events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_events_channel ON sensor_events(channel, timestamp);

    CREATE TABLE IF NOT EXISTS slot_summary (
        date        TEXT NOT NULL,
        slot        INTEGER NOT NULL,
        channel     TEXT NOT NULL,
        active      INTEGER NOT NULL DEFAULT 0,
        event_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (date, slot, channel)
    );

    CREATE TABLE IF NOT EXISTS daily_scores (
        date              TEXT PRIMARY KEY,
        train_days        INTEGER,
        nll_presence      REAL,
        nll_fridge        REAL,
        nll_bathroom      REAL,
        nll_door          REAL,
        nll_total         REAL,
        expected_count    REAL,
        observed_count    INTEGER,
        count_z           REAL,
        composite_z       REAL,
        alert_level       INTEGER DEFAULT 0,
        aw_accuracy       REAL,
        aw_balanced_acc   REAL,
        aw_active_recall  REAL,
        is_learning       INTEGER DEFAULT 1,
        created_at        TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS model_state (
        slot        INTEGER NOT NULL,
        channel     TEXT NOT NULL,
        alpha       REAL NOT NULL DEFAULT 1,
        beta        REAL NOT NULL DEFAULT 1,
        last_updated TEXT,
        PRIMARY KEY (slot, channel)
    );
    """),
    (2, """
    -- Sema versiyonu 2: Sistem durumu tablosu (tatil modu vb.)

    CREATE TABLE IF NOT EXISTS system_state (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT DEFAULT (datetime('now'))
    );
    """),
]


@contextmanager
def get_db(db_path: str):
    """SQLite baglantisi context manager.

    WAL modu ve row_factory aktif.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def _get_current_version(conn: sqlite3.Connection) -> int:
    """Mevcut sema versiyonunu dondur. Tablo yoksa 0."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    if cursor.fetchone() is None:
        return 0
    cursor = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
    return cursor.fetchone()[0]


def _apply_migration(conn: sqlite3.Connection, version: int, sql: str) -> None:
    """Tek bir migration'i uygula ve versiyonu kaydet."""
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        (version,),
    )
    conn.commit()
    logger.info("Migration v%d uyguland", version)


def init_db(db_path: str) -> None:
    """Veritabanini baslat: dizin olustur, tablolari yarat.

    Idempotent: birden fazla kez cagirilabilir.
    """
    # Veri dizinini olustur
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with get_db(db_path) as conn:
        # schema_version tablosunu olustur (migration takibi icin)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version     INTEGER PRIMARY KEY,
                applied_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        current_version = _get_current_version(conn)
        logger.info("Mevcut sema versiyonu: %d", current_version)

        # Bekleyen migration'lari uygula
        for version, sql in MIGRATIONS:
            if version > current_version:
                _apply_migration(conn, version, sql)

        final_version = _get_current_version(conn)
        logger.info("Veritabani hazir, sema versiyonu: %d", final_version)


def cleanup_old_events(db_path: str, retention_days: int) -> int:
    """retention_days gunden eski sensor_events kayitlarini sil.

    Args:
        db_path: Veritabani yolu
        retention_days: Tutulacak gun sayisi

    Returns:
        Silinen kayit sayisi
    """
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime(
        "%Y-%m-%dT00:00:00"
    )
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM sensor_events WHERE timestamp < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        conn.commit()
    if deleted:
        logger.info(
            "Eski eventler temizlendi: %d kayit silindi (retention=%d gun)",
            deleted,
            retention_days,
        )
    return deleted


def run_db_maintenance(db_path: str) -> None:
    """WAL checkpoint ve isteğe bağlı bakim islemleri.

    Her gece calistirilmasi onerilir. VACUUM yerine checkpoint tercih edilir
    (Pi'de dusuk I/O).
    """
    with get_db(db_path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    logger.info("DB bakim tamamlandi: WAL checkpoint (TRUNCATE)")


# ------------------------------------------------------------------ #
#  System State (vacation mode vb.)
# ------------------------------------------------------------------ #

def get_system_state(db_path: str, key: str, default: str = "") -> str:
    """system_state tablosundan key degerini oku.

    Args:
        db_path: Veritabani yolu
        key: Anahtar adi
        default: Bulunamazsa varsayilan deger

    Returns:
        Deger stringi
    """
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM system_state WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_system_state(db_path: str, key: str, value: str) -> None:
    """system_state tablosuna key/value yaz (INSERT OR REPLACE).

    Args:
        db_path: Veritabani yolu
        key: Anahtar adi
        value: Deger stringi
    """
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO system_state (key, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            (key, value),
        )
        conn.commit()


def is_vacation_mode(db_path: str, config: AppConfig) -> bool:
    """Tatil modunda mi? DB state oncelikli, yoksa config'e bak.

    Args:
        db_path: Veritabani yolu
        config: Uygulama konfigurasyonu

    Returns:
        True ise tatil modunda
    """
    db_val = get_system_state(db_path, "vacation_mode", "")
    if db_val:
        return db_val.lower() in ("true", "1", "yes")
    # DB'de yoksa config'ten oku
    return config.system.vacation_mode
