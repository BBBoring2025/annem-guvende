"""FIX 2 Tests: nll_z tek tarafli.

- nll_total < mean -> nll_z == 0
- nll_total >> mean -> nll_z > 0
"""

import pytest

from src.config import AppConfig
from src.database import get_db, init_db
from src.detector.anomaly_scorer import score_day


def _insert_daily_score(db_path, date, nll_total, count_z=0.0, alert_level=0,
                        is_learning=0, train_days=15):
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
def nll_db(tmp_path):
    db_path = str(tmp_path / "nll_test.db")
    init_db(db_path)
    return db_path


def _insert_normal_history(db_path, n_days=10, base_nll=50.0):
    """N gun normal tarihce ekle."""
    for i in range(n_days):
        _insert_daily_score(
            db_path,
            date=f"2025-01-{i + 1:02d}",
            nll_total=base_nll + (i % 3) * 0.5,
        )


def test_low_nll_gives_zero_z(nll_db):
    """nll_total < mean -> nll_z == 0 (tek tarafli, dusuk NLL iyi demek)."""
    _insert_normal_history(nll_db, n_days=10, base_nll=50.0)
    # Hedef gun: NLL cok dusuk (mukemmel uyum)
    _insert_daily_score(nll_db, "2025-01-20", nll_total=30.0, count_z=0.0)

    result = score_day(nll_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.nll_z == 0.0, (
        f"nll_total < mean iken nll_z={result.nll_z}, 0.0 bekleniyor (tek tarafli)"
    )


def test_high_nll_gives_positive_z(nll_db):
    """nll_total >> mean -> nll_z > 0 (yuksek NLL = kotu uyum = risk)."""
    _insert_normal_history(nll_db, n_days=10, base_nll=50.0)
    # Hedef gun: NLL cok yuksek
    _insert_daily_score(nll_db, "2025-01-20", nll_total=70.0, count_z=0.0)

    result = score_day(nll_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.nll_z > 0.0, (
        f"nll_total >> mean iken nll_z={result.nll_z}, > 0 bekleniyor"
    )


def test_slightly_below_mean_gives_zero(nll_db):
    """nll_total biraz < mean -> nll_z == 0."""
    _insert_normal_history(nll_db, n_days=10, base_nll=50.0)
    _insert_daily_score(nll_db, "2025-01-20", nll_total=49.0, count_z=0.0)

    result = score_day(nll_db, _default_config(), target_date="2025-01-20")

    assert result is not None
    assert result.nll_z == 0.0
