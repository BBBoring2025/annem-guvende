"""Sistem metrikleri toplama modulu.

Saf fonksiyonlar: psutil + DB sorgusu ile metrik toplar,
SystemMetrics dataclass dondurur. Side effect yok.
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime

import psutil

from src.database import get_db

logger = logging.getLogger("annem_guvende.heartbeat")


@dataclass
class SystemMetrics:
    """Sistem sagligi metrikleri."""

    cpu_percent: float
    memory_percent: float
    disk_percent: float
    cpu_temp: float | None  # None = Pi degil (macOS, vb.)
    db_size_mb: float
    last_event_age_minutes: float | None  # None = bugun event yok
    today_event_count: int
    uptime_seconds: float


def get_cpu_percent() -> float:
    """CPU kullanim yuzdesi (anlik, non-blocking).

    interval=0: onceki cagriyla arasindaki farki dondurur.
    Ilk cagri 0.0 donebilir, scheduler dongulerinde dogru calisir.
    """
    return psutil.cpu_percent(interval=0)


def get_memory_percent() -> float:
    """RAM kullanim yuzdesi."""
    return psutil.virtual_memory().percent


def get_disk_percent() -> float:
    """Disk kullanim yuzdesi (root partition)."""
    return psutil.disk_usage("/").percent


def get_cpu_temp() -> float | None:
    """Raspberry Pi CPU sicakligi (Celsius).

    Pi disinda None dondurur (macOS, CI, vb.).
    Oncelik: psutil.sensors_temperatures() > sysfs fallback
    """
    # Yontem 1: psutil sensors_temperatures
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            # Pi'de "cpu_thermal" key'i altinda olur
            for key in ("cpu_thermal", "cpu-thermal", "coretemp"):
                if key in temps and temps[key]:
                    return temps[key][0].current
    except (AttributeError, OSError):
        pass

    # Yontem 2: sysfs fallback (Raspberry Pi)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            raw = f.read().strip()
            return int(raw) / 1000.0
    except (FileNotFoundError, OSError, ValueError):
        pass

    return None


def get_uptime_seconds() -> float:
    """Sistem uptime (saniye)."""
    return time.time() - psutil.boot_time()


def get_db_size_mb(db_path: str) -> float:
    """SQLite dosya boyutu (MB).

    Dosya yoksa 0.0 dondurur.
    """
    try:
        return os.path.getsize(db_path) / (1024 * 1024)
    except OSError:
        return 0.0


def get_last_event_age_minutes(
    db_path: str,
    now: datetime | None = None,
) -> float | None:
    """Son sensor event'ten bu yana gecen dakika.

    Bugun hic event yoksa None dondurur.

    Args:
        db_path: Veritabani yolu
        now: Simdiki zaman (test icin override)

    Returns:
        Dakika cinsinden yas veya None
    """
    if now is None:
        now = datetime.now()

    today_str = now.strftime("%Y-%m-%d")

    with get_db(db_path) as conn:
        row = conn.execute(
            """SELECT MAX(timestamp) as last_ts
               FROM sensor_events
               WHERE timestamp >= ?""",
            (f"{today_str}T00:00:00",),
        ).fetchone()

    if row is None or row["last_ts"] is None:
        return None

    try:
        last_ts = datetime.fromisoformat(row["last_ts"])
        delta = (now - last_ts).total_seconds() / 60.0
        return max(0.0, delta)
    except (ValueError, TypeError):
        return None


def get_today_event_count(
    db_path: str,
    now: datetime | None = None,
) -> int:
    """Bugunun toplam sensor event sayisi.

    Args:
        db_path: Veritabani yolu
        now: Simdiki zaman (test icin override)

    Returns:
        Event sayisi
    """
    if now is None:
        now = datetime.now()

    today_str = now.strftime("%Y-%m-%d")

    with get_db(db_path) as conn:
        row = conn.execute(
            """SELECT COUNT(*) as cnt
               FROM sensor_events
               WHERE timestamp >= ? AND timestamp < ?""",
            (f"{today_str}T00:00:00", f"{today_str}T23:59:59"),
        ).fetchone()

    return row["cnt"] if row else 0


def collect_system_metrics(
    db_path: str,
    now: datetime | None = None,
) -> SystemMetrics:
    """Tum sistem metriklerini topla.

    Bu fonksiyon heartbeat payload'i ve watchdog icin
    ortak veri kaynagi.

    Args:
        db_path: Veritabani yolu
        now: Simdiki zaman (test icin override)

    Returns:
        Dolu SystemMetrics dataclass
    """
    return SystemMetrics(
        cpu_percent=get_cpu_percent(),
        memory_percent=get_memory_percent(),
        disk_percent=get_disk_percent(),
        cpu_temp=get_cpu_temp(),
        db_size_mb=get_db_size_mb(db_path),
        last_event_age_minutes=get_last_event_age_minutes(db_path, now),
        today_event_count=get_today_event_count(db_path, now),
        uptime_seconds=get_uptime_seconds(),
    )
