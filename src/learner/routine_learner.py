"""Gunluk rutin ogrenme orkestratoru.

Her gece 00:15'te calisir:
1. Dunku slot_summary verisini oku
2. Mevcut model_state'i yukle (yoksa baslat)
3. GUNCELLEME ONCESI metrikleri hesapla (modeli ne kadar sasirtti?)
4. Posteriori guncelle (Bayesian update)
5. model_state'e kaydet
6. daily_scores'a yaz (composite_z=0.0; detector uzerine yazar)
"""

import logging
from datetime import datetime, timedelta

from src.config import AppConfig
from src.database import get_db
from src.learner.beta_model import BetaPosterior
from src.learner.metrics import DEFAULT_CHANNELS, calculate_daily_metrics, get_channels_from_config

logger = logging.getLogger("annem_guvende.learner")


def run_daily_learning(
    db_path: str,
    config: AppConfig,
    target_date: str | None = None,
) -> None:
    """Gunluk ogrenme pipeline'ini calistir.

    Args:
        db_path: Veritabani yolu
        config: Uygulama konfigurasyonu
        target_date: Hedef tarih (default: dun). Format: YYYY-MM-DD
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Tekrar calistirma korumasi
    if _already_processed(db_path, target_date):
        logger.info("Tarih zaten islenmis, atlaniyor: %s", target_date)
        return

    prior_a = config.model.prior_alpha
    prior_b = config.model.prior_beta
    learning_days = config.model.learning_days
    awake_start = config.model.awake_start_hour * 4
    awake_end = config.model.awake_end_hour * 4
    channels = get_channels_from_config(config)

    # 1. Slot verisi yukle
    slot_data = _load_slot_data(db_path, target_date, channels=channels)
    if slot_data is None:
        logger.warning("Slot verisi bulunamadi: %s", target_date)
        return

    # 2. Model yukle veya baslat
    model = _load_or_initialize_model(db_path, prior_a, prior_b, channels=channels)

    # 3. GUNCELLEME ONCESI metrikler (modeli ne kadar sasirtti?)
    metrics = calculate_daily_metrics(slot_data, model, awake_start, awake_end, channels=channels)

    # 4. Posterior guncelle
    updated_model = _update_posteriors(model, slot_data, channels=channels)

    # 5. model_state'e kaydet
    _save_model_state(db_path, updated_model, target_date, channels=channels)

    # 6. daily_scores'a yaz (composite_z=0.0; detector overwrite edecek)
    train_days = _count_train_days(db_path)
    is_learning = 1 if (train_days + 1) <= learning_days else 0
    _save_daily_scores(
        db_path, target_date, train_days + 1, metrics, 0.0, is_learning
    )

    logger.info(
        "Gunluk ogrenme tamamlandi: %s | train_days=%d | nll_total=%.2f | "
        "is_learning=%d",
        target_date, train_days + 1, metrics["nll_total"],
        is_learning,
    )


def _already_processed(db_path: str, date: str) -> bool:
    """Bu tarih daha once islenmis mi?"""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM daily_scores WHERE date = ?", (date,)
        ).fetchone()
    return row is not None


def _load_slot_data(
    db_path: str, date: str, channels: list[str] | None = None
) -> dict[str, list[int]] | None:
    """slot_summary'den slot verisini yukle.

    Returns:
        {channel: [96 active degeri]} veya veri yoksa None
    """
    ch_list = channels if channels is not None else list(DEFAULT_CHANNELS)
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT slot, channel, active FROM slot_summary WHERE date = ?",
            (date,),
        ).fetchall()

    if not rows:
        return None

    slot_data: dict[str, list[int]] = {ch: [0] * 96 for ch in ch_list}
    for row in rows:
        ch = row["channel"]
        s = row["slot"]
        if ch in slot_data and 0 <= s < 96:
            slot_data[ch][s] = row["active"]

    return slot_data


def _load_or_initialize_model(
    db_path: str, prior_a: float, prior_b: float, channels: list[str] | None = None
) -> dict[str, list[BetaPosterior]]:
    """model_state'ten yukle; bossa N*96 satirlik prior ekle.

    Returns:
        {channel: [96 BetaPosterior]}
    """
    ch_list = channels if channels is not None else list(DEFAULT_CHANNELS)
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT slot, channel, alpha, beta FROM model_state"
        ).fetchall()

    if rows:
        model: dict[str, list[BetaPosterior]] = {
            ch: [BetaPosterior(prior_a, prior_b) for _ in range(96)]
            for ch in ch_list
        }
        for row in rows:
            ch = row["channel"]
            s = row["slot"]
            if ch in model and 0 <= s < 96:
                model[ch][s] = BetaPosterior(row["alpha"], row["beta"])
        return model

    # Ilk calisma: N*96 satir INSERT
    with get_db(db_path) as conn:
        for ch in ch_list:
            for s in range(96):
                conn.execute(
                    "INSERT INTO model_state (slot, channel, alpha, beta) "
                    "VALUES (?, ?, ?, ?)",
                    (s, ch, prior_a, prior_b),
                )
        conn.commit()
    logger.info("model_state baslatildi: %d satir (%d kanal x 96 slot)",
                len(ch_list) * 96, len(ch_list))

    return {
        ch: [BetaPosterior(prior_a, prior_b) for _ in range(96)]
        for ch in ch_list
    }


def _update_posteriors(
    model: dict[str, list[BetaPosterior]],
    slot_data: dict[str, list[int]],
    channels: list[str] | None = None,
) -> dict[str, list[BetaPosterior]]:
    """Tum slotlar icin Bayesian update (immutable - yeni model dondurur)."""
    ch_list = channels if channels is not None else list(DEFAULT_CHANNELS)
    updated = {}
    for ch in ch_list:
        updated[ch] = [
            model[ch][s].update(slot_data[ch][s]) for s in range(96)
        ]
    return updated


def _save_model_state(
    db_path: str,
    model: dict[str, list[BetaPosterior]],
    date: str,
    channels: list[str] | None = None,
) -> None:
    """Guncellenmis model_state'i DB'ye yaz."""
    ch_list = channels if channels is not None else list(DEFAULT_CHANNELS)
    with get_db(db_path) as conn:
        for ch in ch_list:
            for s in range(96):
                conn.execute(
                    "UPDATE model_state SET alpha = ?, beta = ?, last_updated = ? "
                    "WHERE slot = ? AND channel = ?",
                    (model[ch][s].alpha, model[ch][s].beta, date, s, ch),
                )
        conn.commit()


def _count_train_days(db_path: str) -> int:
    """daily_scores'taki kayit sayisi (bugunku dahil degil)."""
    with get_db(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM daily_scores").fetchone()
    return row[0]


def _save_daily_scores(
    db_path: str,
    date: str,
    train_days: int,
    metrics: dict,
    composite_z: float,
    is_learning: int,
) -> None:
    """daily_scores tablosuna INSERT OR REPLACE."""
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_scores (
                date, train_days,
                nll_presence, nll_fridge, nll_bathroom, nll_door, nll_total,
                expected_count, observed_count, count_z,
                composite_z, alert_level,
                aw_accuracy, aw_balanced_acc, aw_active_recall,
                is_learning
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                date, train_days,
                metrics["nll_presence"], metrics["nll_fridge"],
                metrics["nll_bathroom"], metrics["nll_door"],
                metrics["nll_total"],
                metrics["expected_count"], metrics["observed_count"],
                metrics["count_z"],
                composite_z, 0,  # alert_level: Sprint 3'te hesaplanacak
                metrics["aw_accuracy"], metrics["aw_balanced_acc"],
                metrics["aw_active_recall"],
                is_learning,
            ),
        )
        conn.commit()
