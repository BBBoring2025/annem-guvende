"""Uctan uca entegrasyon testleri - 21 gunluk pilot simulasyonu.

Tum pipeline'i test eder:
Simulator -> Collector (slot aggregate) -> Learner -> Detector -> Alerter
"""

from datetime import datetime, timedelta

import pytest

from src.collector.slot_aggregator import aggregate_current_slot, fill_missing_slots
from src.config import AppConfig
from src.database import get_db, init_db
from src.detector.anomaly_scorer import score_day
from src.learner import BetaPosterior, run_daily_learning
from src.learner.metrics import CHANNELS

# --- Yardimci fonksiyonlar ---

def _simulate_one_day(db_path, config, date, channels, sim, anomaly_type=None):
    """Tek gun simulasyonu: event uret -> aggregate -> fill -> learn -> score.

    Args:
        db_path: DB yolu
        config: Uygulama config dict
        date: YYYY-MM-DD
        channels: Kanal listesi
        sim: SensorSimulator instance
        anomaly_type: None=normal, str=anomali tipi

    Returns:
        AnomalyResult | None (score_day sonucu)
    """
    # 1. Event uret
    if anomaly_type:
        sim.generate_anomaly_day(date, anomaly_type)
    else:
        sim.generate_normal_day(date)

    # 2. Tum 96 slot icin aggregate
    year, month, day = map(int, date.split("-"))
    for slot in range(96):
        hour = slot // 4
        minute = (slot % 4) * 15
        dt = datetime(year, month, day, hour, minute)
        aggregate_current_slot(db_path, channels, now=dt)

    # 3. Bos slotlari doldur
    fill_missing_slots(db_path, date, channels)

    # 4. Ogrenme
    run_daily_learning(db_path, config, target_date=date)

    # 5. Skorlama
    return score_day(db_path, config, target_date=date)


# --- Module-scope fixture: 21 gun simulasyonu (tek sefer calisir) ---

@pytest.fixture(scope="module")
def integration_env(tmp_path_factory):
    """21 gunluk uctan uca simulasyon ortami.

    Bir kez calisir, tum testler ayni DB'yi paylaslr (read-only).
    """
    from src.simulator.sensor_simulator import SensorSimulator

    tmp = tmp_path_factory.mktemp("integration")
    db_path = str(tmp / "integration.db")
    init_db(db_path)

    config = AppConfig(
        model={"slot_minutes": 15, "learning_days": 14, "prior_alpha": 1.0, "prior_beta": 1.0, "awake_start_hour": 6, "awake_end_hour": 23},
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
        telegram={"bot_token": "", "chat_ids": []},
    )

    channels = CHANNELS
    sim = SensorSimulator(db_path, seed=42)
    anomaly_day_index = 17  # 0-indexed -> gun 18

    results = {}  # date -> AnomalyResult
    dates = []

    for i in range(21):
        date = (datetime(2025, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
        dates.append(date)

        if i == anomaly_day_index:
            result = _simulate_one_day(
                db_path, config, date, channels, sim, anomaly_type="low_activity"
            )
        else:
            result = _simulate_one_day(db_path, config, date, channels, sim)

        results[date] = result

    return {
        "db_path": db_path,
        "config": config,
        "dates": dates,
        "results": results,
        "anomaly_date": dates[anomaly_day_index],
    }


# --- Testler ---

def test_ci_narrows_after_14_days(integration_env):
    """14 gun sonra ortalama CI genisligi baslangicin %50'sinden az olmali."""
    db_path = integration_env["db_path"]

    initial_ci = BetaPosterior(1.0, 1.0).ci_width  # ~0.95

    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT alpha, beta FROM model_state"
        ).fetchall()

    ci_widths = [BetaPosterior(r["alpha"], r["beta"]).ci_width for r in rows]
    avg_ci = sum(ci_widths) / len(ci_widths)

    assert avg_ci < initial_ci * 0.5, (
        f"CI daralma yetersiz: avg_ci={avg_ci:.4f}, "
        f"esik={initial_ci * 0.5:.4f}"
    )


def test_learning_flag_transition(integration_env):
    """Gun 1-14 is_learning=1, gun 15+ is_learning=0."""
    db_path = integration_env["db_path"]
    dates = integration_env["dates"]

    with get_db(db_path) as conn:
        for i, date in enumerate(dates):
            row = conn.execute(
                "SELECT is_learning, train_days FROM daily_scores WHERE date = ?",
                (date,),
            ).fetchone()

            assert row is not None, f"daily_scores eksik: {date}"

            if i < 14:
                assert row["is_learning"] == 1, (
                    f"Gun {i+1} ({date}): is_learning=1 olmali"
                )
            else:
                assert row["is_learning"] == 0, (
                    f"Gun {i+1} ({date}): is_learning=0 olmali"
                )


def test_anomaly_detected_on_day_18(integration_env):
    """Anomali gunu (gun 18) composite_z > 2.0 olmali."""
    anomaly_date = integration_env["anomaly_date"]
    db_path = integration_env["db_path"]

    # score_day sonucunu kontrol et
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT composite_z, alert_level FROM daily_scores WHERE date = ?",
            (anomaly_date,),
        ).fetchone()

    assert row is not None, f"Anomali gunu daily_scores eksik: {anomaly_date}"
    assert row["composite_z"] > 2.0, (
        f"Anomali gunu composite_z yetersiz: {row['composite_z']:.2f} "
        f"(beklenen > 2.0)"
    )
    assert row["alert_level"] >= 1, (
        f"Anomali gunu alert_level yetersiz: {row['alert_level']}"
    )


def test_normal_days_low_false_alarm(integration_env):
    """Post-learning normal gunlerde ciddi false alarm olmamali.

    alert_level >= 2 (ciddi/acil) false alarm sayilir.
    alert_level = 1 (dikkat) normal varyasyondan kaynaklanabilir.
    Anomali gunu haric max 1 ciddi false alarm kabul edilir.
    """
    dates = integration_env["dates"]
    anomaly_date = integration_env["anomaly_date"]
    db_path = integration_env["db_path"]

    serious_false_alarms = 0

    with get_db(db_path) as conn:
        for date in dates[14:]:  # Gun 15+ (post-learning)
            if date == anomaly_date:
                continue

            row = conn.execute(
                "SELECT composite_z, alert_level FROM daily_scores WHERE date = ?",
                (date,),
            ).fetchone()

            if row and row["alert_level"] >= 2:
                serious_false_alarms += 1

    assert serious_false_alarms <= 1, (
        f"Cok fazla ciddi false alarm: {serious_false_alarms} "
        f"(max 1 kabul edilir)"
    )


def test_all_days_have_slot_data(integration_env):
    """Her gun, her kanal 96 slot verisine sahip olmali."""
    dates = integration_env["dates"]
    db_path = integration_env["db_path"]

    with get_db(db_path) as conn:
        for date in dates:
            for ch in CHANNELS:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM slot_summary "
                    "WHERE date = ? AND channel = ?",
                    (date, ch),
                ).fetchone()

                assert row["cnt"] == 96, (
                    f"{date} / {ch}: {row['cnt']} slot (beklenen 96)"
                )


def test_model_state_alpha_beta_grow(integration_env):
    """model_state'teki alpha + beta toplami gunden gune artmali."""
    db_path = integration_env["db_path"]

    # 21 gun sonra her slot icin alpha + beta >= 2 + 21 = 23
    # (baslangic: alpha=1, beta=1, her gun +1 update)
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT alpha, beta FROM model_state"
        ).fetchall()

    min_total = min(r["alpha"] + r["beta"] for r in rows)

    # 21 update sonrasi: alpha + beta >= 2 + 21 = 23
    assert min_total >= 23, (
        f"model_state alpha+beta minimum={min_total:.1f} (beklenen >= 23)"
    )
