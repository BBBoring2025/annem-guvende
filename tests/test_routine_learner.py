"""Rutin ogrenme entegrasyon testleri - gercek DB, model guncelleme, daily_scores."""

import pytest

from src.config import AppConfig
from src.database import get_db, init_db
from src.learner.routine_learner import run_daily_learning

CHANNELS = ["presence", "fridge", "bathroom", "door"]


def _insert_slot_summary(db_path: str, date: str, active_slots=None):
    """Test icin slot_summary verisi ekle.

    active_slots: None ise gunduz (24-91) aktif, gece pasif.
    Dict ise {channel: [slot_indices]} seklinde ozel deger.
    """
    with get_db(db_path) as conn:
        for ch in CHANNELS:
            for s in range(96):
                if active_slots is None:
                    active = 1 if 24 <= s < 92 else 0
                elif isinstance(active_slots, dict):
                    active = 1 if s in active_slots.get(ch, []) else 0
                else:
                    active = 0
                conn.execute(
                    "INSERT OR REPLACE INTO slot_summary (date, slot, channel, active, event_count) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (date, s, ch, active, active),
                )
        conn.commit()


@pytest.fixture
def learner_db(tmp_path):
    """Ogrenme testleri icin hazir DB."""
    db_path = str(tmp_path / "learner_test.db")
    init_db(db_path)
    return db_path


@pytest.fixture
def learner_config():
    """Ogrenme testleri icin config."""
    return AppConfig(
        model={"slot_minutes": 15, "learning_days": 14, "prior_alpha": 1.0, "prior_beta": 1.0, "awake_start_hour": 6, "awake_end_hour": 23},
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
    )


def test_first_day_initializes_model_state(learner_db, learner_config):
    """Ilk gun: model_state 384 satir (4 kanal x 96 slot) olusturulmali."""
    _insert_slot_summary(learner_db, "2025-01-15")

    run_daily_learning(learner_db, learner_config, target_date="2025-01-15")

    with get_db(learner_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM model_state").fetchone()[0]

    assert count == 384, f"model_state {count} satir, 384 bekleniyor"


def test_daily_scores_written(learner_db, learner_config):
    """daily_scores tablosuna kayit yazilmali (train_days=1, nll_total>0)."""
    _insert_slot_summary(learner_db, "2025-01-15")

    run_daily_learning(learner_db, learner_config, target_date="2025-01-15")

    with get_db(learner_db) as conn:
        row = conn.execute(
            "SELECT * FROM daily_scores WHERE date = '2025-01-15'"
        ).fetchone()

    assert row is not None, "daily_scores'a kayit yazilmadi"
    assert row["train_days"] == 1
    assert row["nll_total"] > 0
    assert row["is_learning"] == 1  # learning_days=14 icinde


def test_active_slot_updates_alpha(learner_db, learner_config):
    """active=1 slot -> alpha artmis (2.0), beta ayni (1.0)."""
    # Tum slotlar aktif olan bir gun
    active_all = {ch: list(range(96)) for ch in CHANNELS}
    _insert_slot_summary(learner_db, "2025-01-15", active_slots=active_all)

    run_daily_learning(learner_db, learner_config, target_date="2025-01-15")

    with get_db(learner_db) as conn:
        row = conn.execute(
            "SELECT alpha, beta FROM model_state WHERE slot = 0 AND channel = 'presence'"
        ).fetchone()

    # prior(1,1) + active=1 -> alpha=2, beta=1
    assert row["alpha"] == 2.0, f"alpha={row['alpha']}, 2.0 bekleniyor"
    assert row["beta"] == 1.0, f"beta={row['beta']}, 1.0 bekleniyor"


def test_three_consecutive_days(learner_db, learner_config):
    """3 ardisik gun -> train_days=3."""
    for i, date in enumerate(["2025-01-15", "2025-01-16", "2025-01-17"]):
        _insert_slot_summary(learner_db, date)
        run_daily_learning(learner_db, learner_config, target_date=date)

    with get_db(learner_db) as conn:
        row = conn.execute(
            "SELECT train_days FROM daily_scores WHERE date = '2025-01-17'"
        ).fetchone()

    assert row["train_days"] == 3, f"train_days={row['train_days']}, 3 bekleniyor"


def test_duplicate_date_skipped(learner_db, learner_config):
    """Ayni tarih iki kez calistirilirsa ikincisi atlanmali."""
    _insert_slot_summary(learner_db, "2025-01-15")

    run_daily_learning(learner_db, learner_config, target_date="2025-01-15")
    run_daily_learning(learner_db, learner_config, target_date="2025-01-15")

    with get_db(learner_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM daily_scores WHERE date = '2025-01-15'"
        ).fetchone()[0]

    assert count == 1, "Tekrar calistirma korumasi calismadi"


def test_no_slot_data_skips(learner_db, learner_config):
    """Slot verisi olmayan tarih -> hata vermeden atlanmali."""
    # slot_summary bos - veri eklemiyoruz
    run_daily_learning(learner_db, learner_config, target_date="2025-01-15")

    with get_db(learner_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM daily_scores").fetchone()[0]

    assert count == 0, "Veri olmadan daily_scores'a yazildi"


def test_is_learning_flag_after_14_days(learner_db, learner_config):
    """14 gun sonra is_learning=0 olmali (learning_days=14)."""
    for day in range(1, 16):
        date = f"2025-01-{day:02d}"
        _insert_slot_summary(learner_db, date)
        run_daily_learning(learner_db, learner_config, target_date=date)

    with get_db(learner_db) as conn:
        # 14. gun: train_days=14, is_learning=1
        row_14 = conn.execute(
            "SELECT is_learning FROM daily_scores WHERE date = '2025-01-14'"
        ).fetchone()
        # 15. gun: train_days=15, is_learning=0
        row_15 = conn.execute(
            "SELECT is_learning FROM daily_scores WHERE date = '2025-01-15'"
        ).fetchone()

    assert row_14["is_learning"] == 1, "14. gun hala ogrenme doneminde olmali"
    assert row_15["is_learning"] == 0, "15. gun ogrenme donemi bitmis olmali"
