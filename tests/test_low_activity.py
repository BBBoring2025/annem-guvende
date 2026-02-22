"""KRITIK: Dusuk aktivite gunu composite_z > 2.0 uretmeli.

Bu test Sprint 3'un temel garantisini dogrular:
Anne hic hareket etmemis veya cok az hareket etmis gun,
anomali skoru olarak BELIRGIN sekilde ortaya cikmali.

v3 buginin tekrarlanmasini engeller.
"""

import pytest

from src.config import AppConfig
from src.database import get_db, init_db
from src.detector.anomaly_scorer import score_day
from src.learner.routine_learner import run_daily_learning

CHANNELS = ["presence", "fridge", "bathroom", "door"]


def _insert_daily_score(
    db_path: str, date: str, nll_total: float, count_z: float,
    alert_level: int = 0, is_learning: int = 0,
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
            VALUES (?, 15, ?, ?, 0.0, ?, ?,
                    10.0, 10.0, 10.0, 10.0,
                    100.0, 100, 0.8, 0.8, 0.8)""",
            (date, nll_total, count_z, alert_level, is_learning),
        )
        conn.commit()


def _insert_slot_summary(db_path: str, date: str, active_daytime: bool = True):
    """slot_summary verisi ekle. active_daytime=True: gunduz aktif, gece pasif."""
    with get_db(db_path) as conn:
        for ch in CHANNELS:
            for s in range(96):
                if active_daytime:
                    active = 1 if 24 <= s < 92 else 0
                else:
                    active = 0  # hic aktivite yok
                conn.execute(
                    "INSERT OR REPLACE INTO slot_summary "
                    "(date, slot, channel, active, event_count) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (date, s, ch, active, active),
                )
        conn.commit()


def _default_config():
    return AppConfig(
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
        model={"slot_minutes": 15, "learning_days": 14, "prior_alpha": 1.0, "prior_beta": 1.0, "awake_start_hour": 6, "awake_end_hour": 23},
    )


@pytest.fixture
def low_activity_db(tmp_path):
    """Dusuk aktivite testleri icin hazir DB."""
    db_path = str(tmp_path / "low_activity_test.db")
    init_db(db_path)
    return db_path


def test_zero_activity_day_high_composite_z(low_activity_db):
    """Sifir aktivite gunu -> composite_z > 2.0.

    20 normal gun sonrasi, NLL cok yuksek + count_z cok negatif.
    """
    # 20 normal gun tarihcesi
    for i in range(20):
        _insert_daily_score(
            low_activity_db,
            date=f"2025-01-{i + 1:02d}",
            nll_total=45.0 + (i % 3) * 0.3,  # stabil NLL
            count_z=0.2,
            alert_level=0,
            is_learning=0,
        )

    # Sifir aktivite gunu: NLL cok yuksek, count_z cok negatif
    _insert_daily_score(
        low_activity_db, "2025-02-01",
        nll_total=120.0,  # normal ~45, bu cok yuksek
        count_z=-8.0,     # hic event yok
    )

    result = score_day(low_activity_db, _default_config(), target_date="2025-02-01")

    assert result is not None
    assert result.composite_z > 2.0, (
        f"Sifir aktivite composite_z={result.composite_z:.2f}, 2.0'den buyuk olmali!"
    )
    assert result.alert_level >= 1


def test_low_count_risk_triggers(low_activity_db):
    """Dusuk event sayisi: count_z=-3.0 -> count_risk=3.0, alert_level >= 2."""
    for i in range(10):
        _insert_daily_score(
            low_activity_db, f"2025-01-{i + 1:02d}",
            nll_total=50.0, count_z=0.0,
            alert_level=0, is_learning=0,
        )
    _insert_daily_score(
        low_activity_db, "2025-02-01",
        nll_total=50.0,  # NLL normal
        count_z=-3.0,     # ama event sayisi dusuk
    )

    result = score_day(low_activity_db, _default_config(), target_date="2025-02-01")

    assert result is not None
    assert result.count_risk == 3.0
    assert result.composite_z >= 3.0
    assert result.alert_level >= 2, (
        f"count_z=-3.0 ile alert_level={result.alert_level}, >= 2 olmali!"
    )


def test_high_activity_no_false_alarm(low_activity_db):
    """Fazla aktivite (count_z=+2.0) -> count_risk=0, false alarm yok."""
    for i in range(10):
        _insert_daily_score(
            low_activity_db, f"2025-01-{i + 1:02d}",
            nll_total=50.0, count_z=0.0,
            alert_level=0, is_learning=0,
        )
    _insert_daily_score(
        low_activity_db, "2025-02-01",
        nll_total=50.5,  # NLL normal aralıkta
        count_z=2.0,      # fazla event (riskli degil)
    )

    result = score_day(low_activity_db, _default_config(), target_date="2025-02-01")

    assert result is not None
    assert result.count_risk == 0.0, (
        "Pozitif count_z risk olusturmamali!"
    )
    assert result.alert_level == 0, (
        f"Fazla aktivite ile alert_level={result.alert_level}, 0 olmali!"
    )


def test_end_to_end_zero_activity_full_pipeline(low_activity_db):
    """Uctan uca: 15 gun learner ile egit, sonra sifir aktivite gunu -> alert >= 1.

    Bu test learner + detector entegrasyonunu dogrular.
    """
    config = _default_config()

    # 15 normal gun: learner ile egit (gunduz aktif, gece pasif)
    for day in range(1, 16):
        date = f"2025-01-{day:02d}"
        _insert_slot_summary(low_activity_db, date, active_daytime=True)
        run_daily_learning(low_activity_db, config, target_date=date)

    # 16. gun: SIFIR aktivite (anomali!)
    _insert_slot_summary(low_activity_db, "2025-01-16", active_daytime=False)
    run_daily_learning(low_activity_db, config, target_date="2025-01-16")

    # Simdi score_day ile degerlendirme
    result = score_day(low_activity_db, config, target_date="2025-01-16")

    assert result is not None
    assert result.alert_level >= 1, (
        f"Sifir aktivite gunu alert_level={result.alert_level}, >= 1 olmali! "
        f"composite_z={result.composite_z:.2f}"
    )
