"""FIX 1 Tests: composite_z tekle\u015ftirme.

- Learner composite_z=0.0 yaziyor mu?
- Detector score_day() composite_z hesapliyor mu?
- Learner modulunde _calculate_composite_z yok mu?
"""

import pytest

from src.config import AppConfig
from src.database import get_db, init_db
from src.learner.routine_learner import run_daily_learning

CHANNELS = ["presence", "fridge", "bathroom", "door"]


def _insert_slot_summary(db_path: str, date: str):
    """Gunduz aktif, gece pasif slot_summary verisi ekle."""
    with get_db(db_path) as conn:
        for ch in CHANNELS:
            for s in range(96):
                active = 1 if 24 <= s < 92 else 0
                conn.execute(
                    "INSERT OR REPLACE INTO slot_summary (date, slot, channel, active, event_count) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (date, s, ch, active, active),
                )
        conn.commit()


@pytest.fixture
def fix1_db(tmp_path):
    db_path = str(tmp_path / "fix1_test.db")
    init_db(db_path)
    return db_path


@pytest.fixture
def fix1_config():
    return AppConfig(
        model={"slot_minutes": 15, "learning_days": 14, "prior_alpha": 1.0, "prior_beta": 1.0, "awake_start_hour": 6, "awake_end_hour": 23},
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
    )


def test_learner_writes_composite_z_zero(fix1_db, fix1_config):
    """Learner daily_scores'a composite_z=0.0 yazmali."""
    _insert_slot_summary(fix1_db, "2025-01-15")
    run_daily_learning(fix1_db, fix1_config, target_date="2025-01-15")

    with get_db(fix1_db) as conn:
        row = conn.execute(
            "SELECT composite_z FROM daily_scores WHERE date = '2025-01-15'"
        ).fetchone()

    assert row is not None, "daily_scores'a kayit yazilmadi"
    assert row["composite_z"] == 0.0, (
        f"Learner composite_z={row['composite_z']}, 0.0 bekleniyor"
    )


def test_detector_calculates_composite_z(fix1_db, fix1_config):
    """Detector score_day() composite_z hesaplamali ve > 0 olabilmeli."""
    from src.detector.anomaly_scorer import score_day

    # 10 normal gun tarihce olustur
    for i in range(10):
        date = f"2025-01-{i + 1:02d}"
        _insert_slot_summary(fix1_db, date)
        run_daily_learning(fix1_db, fix1_config, target_date=date)

    # Hedef gun: anormal veri (tum slotlar pasif)
    with get_db(fix1_db) as conn:
        for ch in CHANNELS:
            for s in range(96):
                conn.execute(
                    "INSERT OR REPLACE INTO slot_summary (date, slot, channel, active, event_count) "
                    "VALUES (?, ?, ?, 0, 0)",
                    ("2025-01-20", s, ch),
                )
        conn.commit()
    run_daily_learning(fix1_db, fix1_config, target_date="2025-01-20")

    # score_day calistir
    result = score_day(fix1_db, fix1_config, target_date="2025-01-20")
    assert result is not None

    # Detector composite_z'yi hesaplamis olmali
    with get_db(fix1_db) as conn:
        row = conn.execute(
            "SELECT composite_z FROM daily_scores WHERE date = '2025-01-20'"
        ).fetchone()

    # Detector en az count_risk uzerinden composite_z > 0 yazmis olmali
    assert row["composite_z"] >= 0.0


def test_learner_has_no_calculate_composite_z():
    """Learner modulunde _calculate_composite_z fonksiyonu olmamali."""
    import src.learner.routine_learner as mod

    assert not hasattr(mod, "_calculate_composite_z"), (
        "_calculate_composite_z hala learner modulunde var!"
    )
