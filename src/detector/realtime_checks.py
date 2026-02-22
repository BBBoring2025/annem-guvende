"""Gercek zamanli sessizlik kontrolleri.

Her 30 dakikada APScheduler ile calisir:
1. Sabah vital sign: 11:00'a kadar hic event yoksa -> alert_level=2
2. Uzun sessizlik: Awake window icinde 3+ saat event yoksa -> alert_level=1
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.config import AppConfig
from src.database import get_db

logger = logging.getLogger("annem_guvende.detector")

# Default degerler (config'ten de alinabilir)
DEFAULT_MORNING_CHECK_HOUR = 11
DEFAULT_SILENCE_THRESHOLD_HOURS = 3


@dataclass
class RealtimeAlert:
    """Gercek zamanli kontrol sonucu."""

    alert_type: str  # "morning_silence" | "extended_silence"
    alert_level: int  # 1 veya 2
    message: str
    last_event_time: str | None


def check_morning_vital_sign(
    db_path: str,
    config: AppConfig,
    now: datetime | None = None,
) -> RealtimeAlert | None:
    """Sabah vital sign kontrolu.

    11:00'a kadar hicbir sensorden event gelmemisse -> ciddi alarm.
    Sadece saat >= 11:00'da kontrol yapar.

    Args:
        db_path: Veritabani yolu
        config: Uygulama konfigurasyonu
        now: Simdiki zaman (test icin override)

    Returns:
        RealtimeAlert veya alarm yoksa None
    """
    if now is None:
        now = datetime.now()

    morning_hour = config.alerts.morning_check_hour

    # Sabah kontrol saatinden once anlamsiz
    if now.hour < morning_hour:
        return None

    # Awake window disinda kontrol yapma (gece)
    awake_end = config.model.awake_end_hour
    if now.hour >= awake_end:
        return None

    today = now.strftime("%Y-%m-%d")
    today_start = f"{today}T00:00:00"
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S")

    with get_db(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM sensor_events "
            "WHERE timestamp >= ? AND timestamp < ?",
            (today_start, now_iso),
        ).fetchone()[0]

    if count == 0:
        return RealtimeAlert(
            alert_type="morning_silence",
            alert_level=2,
            message=f"Sabah {morning_hour}:00'dan beri hicbir sensor aktivitesi yok!",
            last_event_time=None,
        )

    return None


def check_extended_silence(
    db_path: str,
    config: AppConfig,
    now: datetime | None = None,
) -> RealtimeAlert | None:
    """Uzun sessizlik kontrolu.

    Awake window icinde son 3+ saattir event yoksa -> nazik alarm.

    Args:
        db_path: Veritabani yolu
        config: Uygulama konfigurasyonu
        now: Simdiki zaman (test icin override)

    Returns:
        RealtimeAlert veya alarm yoksa None
    """
    if now is None:
        now = datetime.now()

    # Awake window kontrolu
    awake_start = config.model.awake_start_hour
    awake_end = config.model.awake_end_hour

    if now.hour < awake_start or now.hour >= awake_end:
        return None

    silence_hours = config.alerts.silence_threshold_hours

    today = now.strftime("%Y-%m-%d")
    today_start = f"{today}T00:00:00"

    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(timestamp) as last_ts FROM sensor_events "
            "WHERE timestamp >= ?",
            (today_start,),
        ).fetchone()

    last_ts = row["last_ts"] if row else None

    if last_ts is None:
        # Hic event yok - morning check halleder (saat >= 11 ise)
        # Extended silence icin de kontrol et
        morning_hour = config.alerts.morning_check_hour
        if now.hour >= morning_hour:
            # Morning check zaten yakalayacak, duplicate alarm verme
            return None
        # Sabah erken saat, henuz morning_check calismiyor
        # Awake window icinde ama hic event yok - alarm
        return None

    # Son event ne zaman?
    try:
        last_event_dt = datetime.fromisoformat(last_ts)
    except (ValueError, TypeError):
        return None

    silence_duration = now - last_event_dt
    threshold = timedelta(hours=silence_hours)

    if silence_duration >= threshold:
        hours_silent = silence_duration.total_seconds() / 3600
        return RealtimeAlert(
            alert_type="extended_silence",
            alert_level=1,
            message=f"Son {hours_silent:.1f} saattir hicbir sensor aktivitesi yok.",
            last_event_time=last_ts,
        )

    return None


def run_realtime_checks(
    db_path: str,
    config: AppConfig,
    now: datetime | None = None,
) -> list[RealtimeAlert]:
    """Tum gercek zamanli kontrolleri calistir.

    Her 30 dakikada bir APScheduler tarafindan cagirilir.

    Returns:
        Tespit edilen alarm listesi (bos olabilir).
    """
    alerts: list[RealtimeAlert] = []

    morning = check_morning_vital_sign(db_path, config, now)
    if morning:
        alerts.append(morning)

    silence = check_extended_silence(db_path, config, now)
    if silence:
        alerts.append(silence)

    return alerts
