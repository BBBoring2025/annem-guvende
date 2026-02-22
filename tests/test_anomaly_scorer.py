"""Anomali skorlama testleri - bilinen veriyle z-skoru hesaplama."""

import pytest

from src.config import AppConfig
from src.database import get_db, init_db
from src.detector.anomaly_scorer import score_day
from src.detector.history_manager import get_normal_stats


def _insert_daily_score(
    db_path: str,
    date: str,
    nll_total: float,
    count_z: float,
    alert_level: int = 0,
    is_learning: int = 0,
    train_days: int = 15,
):
    """Test icin daily_scores satirlari ekle."""
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_scores
            (date, train_days, nll_total, count_z, composite_z,
             alert_level, is_learning,
             nll_presence, nll_fridge, nll_bathroom, nll_door,
             expected_count, observed_count,
             aw_accuracy, aw_balanced_acc, aw_active_recall)
            VALUES (?, ?, ?, ?, 0.0, ?, ?, 10.0, 10.0, 10.0, 10.0,
                    100.0, 100, 0.8, 0.8, 0.8)""",
            (date, train_days, nll_total, count_z, alert_level, is_learning),
        )
        conn.commit()


def _default_config():
    return AppConfig(
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
        model={"learning_days": 14},
    )


@pytest.fixture
def scorer_db(tmp_path):
    """Anomali skorlama testleri icin hazir DB."""
    db_path = str(tmp_path / "scorer_test.db")
    init_db(db_path)
    return db_path


def _insert_normal_history(db_path, n_days=10, base_nll=50.0):
    """N gun normal tarihce ekle (kuçuk NLL varyansı)."""
    for i in range(n_days):
        _insert_daily_score(
            db_path,
            date=f"2025-01-{i + 1:02d}",
            nll_total=base_nll + (i % 3) * 0.5,  # 50.0, 50.5, 51.0, ...
            count_z=0.3,
            alert_level=0,
            is_learning=0,
        )


def test_score_day_normal(scorer_db):
    """Normal gun: dusuk nll_z, composite_z < 2.0, alert_level=0."""
    _insert_normal_history(scorer_db, n_days=10, base_nll=50.0)
    # Hedef gun: NLL normal aralıkta
    _insert_daily_score(scorer_db, "2025-01-20", nll_total=50.5, count_z=0.2)

    result = score_day(scorer_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.nll_z < 2.0
    assert result.count_risk == 0.0  # pozitif count_z -> risk yok
    assert result.composite_z < 2.0
    assert result.alert_level == 0


def test_score_day_high_nll_anomaly(scorer_db):
    """Yuksek NLL anomalisi: nll_z > 4.0, alert_level=3."""
    _insert_normal_history(scorer_db, n_days=10, base_nll=50.0)
    # Hedef gun: NLL cok yuksek (anomali)
    _insert_daily_score(scorer_db, "2025-01-20", nll_total=70.0, count_z=0.0)

    result = score_day(scorer_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.nll_z > 4.0
    assert result.composite_z > 4.0
    assert result.alert_level == 3


def test_score_day_low_count_anomaly(scorer_db):
    """Dusuk event sayisi: count_z=-3.5 -> count_risk=3.5, alert_level >= 2."""
    _insert_normal_history(scorer_db, n_days=10, base_nll=50.0)
    _insert_daily_score(scorer_db, "2025-01-20", nll_total=50.5, count_z=-3.5)

    result = score_day(scorer_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.count_risk == 3.5
    assert result.composite_z >= 3.0
    assert result.alert_level >= 2


def test_score_day_count_risk_one_sided(scorer_db):
    """Fazla event (count_z=+3.0) -> count_risk=0 (tek tarafli)."""
    _insert_normal_history(scorer_db, n_days=10, base_nll=50.0)
    _insert_daily_score(scorer_db, "2025-01-20", nll_total=50.5, count_z=3.0)

    result = score_day(scorer_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.count_risk == 0.0  # pozitif count_z riskli degil


def test_score_day_insufficient_history(scorer_db):
    """Yetersiz tarihce (< 7 gun) -> nll_z=0, sadece count_risk."""
    # Sadece 5 normal gun (min_train_days=7'den az)
    _insert_normal_history(scorer_db, n_days=5, base_nll=50.0)
    _insert_daily_score(scorer_db, "2025-01-20", nll_total=70.0, count_z=-2.5)

    result = score_day(scorer_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.nll_z == 0.0  # tarihce yetersiz
    assert result.count_risk == 2.5
    assert result.composite_z == 2.5


def test_score_day_learning_phase_capped(scorer_db):
    """Ogrenme donemi: is_learning=1 -> max alert_level=1."""
    _insert_normal_history(scorer_db, n_days=10, base_nll=50.0)
    _insert_daily_score(
        scorer_db, "2025-01-20", nll_total=70.0, count_z=-4.0, is_learning=1
    )

    result = score_day(scorer_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.composite_z > 4.0  # skor yuksek
    assert result.alert_level == 1  # ama ogrenme doneminde cap


def test_score_day_overwrites_daily_scores(scorer_db):
    """score_day daily_scores'taki composite_z ve alert_level'i gunceller."""
    _insert_normal_history(scorer_db, n_days=10, base_nll=50.0)
    _insert_daily_score(scorer_db, "2025-01-20", nll_total=70.0, count_z=-4.0)

    # Baslangicta composite_z=0, alert_level=0
    with get_db(scorer_db) as conn:
        before = conn.execute(
            "SELECT composite_z, alert_level FROM daily_scores WHERE date = '2025-01-20'"
        ).fetchone()
    assert before["composite_z"] == 0.0
    assert before["alert_level"] == 0

    # score_day calistir
    score_day(scorer_db, _default_config(), target_date="2025-01-20")

    # Guncellenmis degerler
    with get_db(scorer_db) as conn:
        after = conn.execute(
            "SELECT composite_z, alert_level FROM daily_scores WHERE date = '2025-01-20'"
        ).fetchone()
    assert after["composite_z"] > 0.0
    assert after["alert_level"] > 0


def test_score_day_excludes_anomaly_days_from_history(scorer_db):
    """Anomali gunleri tarihceden haric tutulur."""
    # 7 normal gun
    for i in range(7):
        _insert_daily_score(
            scorer_db, f"2025-01-{i + 1:02d}",
            nll_total=50.0, count_z=0.0, alert_level=0, is_learning=0,
        )
    # 3 anomali gunu (alert_level=2) - tarihceye dahil olmamali
    for i in range(3):
        _insert_daily_score(
            scorer_db, f"2025-01-{i + 8:02d}",
            nll_total=80.0, count_z=-5.0, alert_level=2, is_learning=0,
        )

    stats = get_normal_stats(scorer_db, max_days=30, min_days=7)
    assert stats.ready is True
    assert stats.n_days == 7  # sadece normal gunler


def test_score_day_excludes_learning_days_from_history(scorer_db):
    """Ogrenme donemi gunleri tarihceden haric tutulur."""
    # 14 ogrenme gunu
    for i in range(14):
        _insert_daily_score(
            scorer_db, f"2025-01-{i + 1:02d}",
            nll_total=50.0, count_z=0.0, alert_level=0, is_learning=1,
        )
    # 6 normal gun (< 7 min)
    for i in range(6):
        _insert_daily_score(
            scorer_db, f"2025-01-{i + 15:02d}",
            nll_total=50.0, count_z=0.0, alert_level=0, is_learning=0,
        )

    stats = get_normal_stats(scorer_db, max_days=30, min_days=7)
    assert stats.ready is False  # 6 < 7


def test_score_day_no_data_returns_none(scorer_db):
    """daily_scores'ta veri yoksa None dondurur."""
    result = score_day(scorer_db, _default_config(), target_date="2025-01-20")
    assert result is None
