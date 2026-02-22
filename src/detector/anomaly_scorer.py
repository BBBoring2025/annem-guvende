"""Gunluk anomali skoru hesaplama.

Her gece 00:20'de calisir (learner'dan 5dk sonra):
1. daily_scores'tan dunku nll_total ve count_z oku
2. Tarihsel normal gunlerin istatistiklerini al
3. NLL z-skoru (tek tarafli: sadece yuksek NLL riskli) + count risk (tek tarafli) hesapla
4. composite_z ve alert_level belirle
5. daily_scores'i guncelle (UPDATE)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.config import AppConfig
from src.database import get_db
from src.detector.history_manager import get_normal_stats
from src.detector.threshold_engine import get_alert_level

logger = logging.getLogger("annem_guvende.detector")


@dataclass
class AnomalyResult:
    """Gunluk anomali skorlama sonucu."""

    date: str
    nll_z: float
    count_z: float
    count_risk: float
    composite_z: float
    alert_level: int


def score_day(
    db_path: str,
    config: AppConfig,
    target_date: str | None = None,
) -> AnomalyResult | None:
    """Belirtilen gun icin anomali skoru hesapla ve daily_scores'i guncelle.

    Args:
        db_path: Veritabani yolu
        config: Uygulama konfigurasyonu
        target_date: Hedef tarih (default: dun). Format: YYYY-MM-DD

    Returns:
        AnomalyResult veya veri yoksa None
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 1. daily_scores'tan oku
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT nll_total, count_z, is_learning FROM daily_scores WHERE date = ?",
            (target_date,),
        ).fetchone()

    if row is None:
        logger.warning("daily_scores'ta veri yok: %s", target_date)
        return None

    nll_total = row["nll_total"]
    count_z = row["count_z"]
    is_learning = row["is_learning"]

    # 2. Tarihsel istatistikler (skorlanan gunu haric tut)
    min_train_days = config.alerts.min_train_days
    history = get_normal_stats(
        db_path, max_days=30, min_days=min_train_days, exclude_date=target_date
    )

    # 3. Skorlama
    if history.ready:
        # Tek tarafli: sadece yuksek NLL (beklenenden kotu uyum) riskli
        nll_z = max(0.0, (nll_total - history.mean_nll) / history.std_nll)
    else:
        nll_z = 0.0

    # Tek tarafli count risk: sadece "az" yonu riskli
    count_risk = max(0.0, -count_z)

    # Composite: en yuksek risk sinyali
    composite_z = max(nll_z, count_risk)

    # 4. Alarm seviyesi
    alert_level = get_alert_level(composite_z, config)

    # Ogrenme doneminde max alert_level=1
    if is_learning == 1:
        alert_level = min(alert_level, 1)

    # 5. daily_scores guncelle
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE daily_scores SET composite_z = ?, alert_level = ? WHERE date = ?",
            (composite_z, alert_level, target_date),
        )
        conn.commit()

    result = AnomalyResult(
        date=target_date,
        nll_z=nll_z,
        count_z=count_z,
        count_risk=count_risk,
        composite_z=composite_z,
        alert_level=alert_level,
    )

    logger.info(
        "Anomali skoru: %s | nll_z=%.2f | count_risk=%.2f | "
        "composite_z=%.2f | alert_level=%d",
        target_date, nll_z, count_risk, composite_z, alert_level,
    )

    return result


def run_daily_scoring(db_path: str, config: AppConfig) -> None:
    """APScheduler tarafindan 00:20'de cagirilir."""
    result = score_day(db_path, config)
    if result is None:
        logger.warning("Gunluk skorlama: veri bulunamadi")
