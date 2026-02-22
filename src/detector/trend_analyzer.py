"""Uzun vadeli trend analizi — Kirilganlik Endeksi (Sprint 14).

Son N gunluk sensor verilerine bakarak kanal bazli trend hesaplar.
Harici ML kutuphanesi kullanmaz — saf Python OLS lineer regresyon.

Kullanim alanlari:
- Banyo kullanim artisi: idrar yolu enfeksiyonu veya sindirim sorunu habercisi
- Hareket azalisi: yorgunluk veya motivasyon dusuklufu habercisi
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.database import get_db

logger = logging.getLogger("annem_guvende.detector")


def linear_regression_slope(values: list[float]) -> float:
    """Basit OLS ile egim hesapla.

    x = [0, 1, 2, ..., n-1], y = values.
    Harici kutuphane gerektirmez.

    Args:
        values: Zaman serisindeki degerler (kronolojik sira).

    Returns:
        Egim (slope). Pozitif = artis, negatif = azalis.
    """
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def get_daily_event_counts(
    db_path: str,
    channel: str,
    days: int,
    now: datetime | None = None,
) -> list[tuple[str, int]]:
    """Kanal bazli gunluk event sayilarini cek, eksik gunleri 0 ile doldur.

    ONEMLI: SQL GROUP BY hic event olmayan gunleri atlar.
    Bu fonksiyon tam bir takvim listesi olusturarak eksik gunlere 0 atar.
    Boylece lineer regresyon dogru calisir.

    Args:
        db_path: Veritabani yolu.
        channel: Kanal adi (orn. "bathroom", "presence").
        days: Kac gunluk veri cekilecek.
        now: Simdiki zaman (test icin override).

    Returns:
        Kronolojik sirada [(date_str, count), ...] — tam `days` eleman.
    """
    now = now or datetime.now()
    today = now.date()

    # 1. Tam takvim listesi olustur
    calendar = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        calendar.append(d.isoformat())

    # 2. SQL'den kanal bazli gunluk count cek
    start_date = calendar[0] + "T00:00:00"
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT DATE(timestamp) AS d, COUNT(*) AS cnt "
            "FROM sensor_events "
            "WHERE channel = ? AND timestamp >= ? "
            "GROUP BY d",
            (channel, start_date),
        ).fetchall()

    # 3. SQL sonuclarini dict'e donustur
    count_map: dict[str, int] = {row["d"]: row["cnt"] for row in rows}

    # 4. Takvimle esle, eksik gunlere 0 ata
    return [(d, count_map.get(d, 0)) for d in calendar]


def calculate_channel_trend(
    db_path: str,
    channel: str,
    days: int = 30,
    min_days: int = 14,
    now: datetime | None = None,
) -> float | None:
    """Kanal event count trendi. Pozitif=artis, negatif=azalis.

    Args:
        db_path: Veritabani yolu.
        channel: Kanal adi.
        days: Analiz periyodu (gun).
        min_days: Minimum veri gunu (altinda None don).
        now: Simdiki zaman (test icin override).

    Returns:
        Egim (float) veya yetersiz veri icin None.
    """
    daily_counts = get_daily_event_counts(db_path, channel, days, now=now)
    if len(daily_counts) < min_days:
        return None
    values = [float(count) for _, count in daily_counts]
    return linear_regression_slope(values)


def analyze_all_trends(
    db_path: str,
    channels: list[str],
    days: int = 30,
    min_days: int = 14,
    now: datetime | None = None,
) -> dict[str, float | None]:
    """Tum kanallarin trend analizini yap.

    Args:
        db_path: Veritabani yolu.
        channels: Kanal listesi.
        days: Analiz periyodu (gun).
        min_days: Minimum veri gunu.
        now: Simdiki zaman (test icin override).

    Returns:
        {kanal: egim_veya_None} dict'i.
    """
    return {
        ch: calculate_channel_trend(db_path, ch, days, min_days, now=now)
        for ch in channels
    }
