"""Tarihsel NLL istatistikleri - rolling normal gun ortalamalari.

Son N normal gunun (alert_level=0, is_learning=0) NLL mean/std'ini hesaplar.
Outlier'lari (onceki anomali gunleri) ve ogrenme donemi gunlerini haric tutar.
"""

import statistics
from dataclasses import dataclass

from src.database import get_db


@dataclass
class HistoryStats:
    """Tarihsel NLL istatistikleri."""

    ready: bool
    mean_nll: float = 0.0
    std_nll: float = 1.0
    n_days: int = 0


def get_normal_stats(
    db_path: str,
    max_days: int = 30,
    min_days: int = 7,
    exclude_date: str | None = None,
) -> HistoryStats:
    """Son N normal gunun NLL istatistiklerini hesapla.

    Args:
        db_path: Veritabani yolu
        max_days: En fazla kac gun geriye bak (default 30)
        min_days: Minimum kac gun gerekli (default 7)
        exclude_date: Bu tarihi haric tut (skorlanan gun)

    Returns:
        HistoryStats: ready=False ise yetersiz veri
    """
    with get_db(db_path) as conn:
        if exclude_date:
            rows = conn.execute(
                "SELECT nll_total FROM daily_scores "
                "WHERE alert_level = 0 AND is_learning = 0 AND date != ? "
                "ORDER BY date DESC LIMIT ?",
                (exclude_date, max_days),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT nll_total FROM daily_scores "
                "WHERE alert_level = 0 AND is_learning = 0 "
                "ORDER BY date DESC LIMIT ?",
                (max_days,),
            ).fetchall()

    if len(rows) < min_days:
        return HistoryStats(ready=False)

    nlls = [r["nll_total"] for r in rows]
    mean_nll = statistics.mean(nlls)
    std_nll = statistics.stdev(nlls) if len(nlls) > 1 else 1.0

    # std=0 korumasi (tum NLL degerleri ayni ise)
    if std_nll == 0.0:
        std_nll = 1.0

    return HistoryStats(
        ready=True,
        mean_nll=mean_nll,
        std_nll=std_nll,
        n_days=len(nlls),
    )
