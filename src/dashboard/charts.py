"""Dashboard veri katmani - DB sorgulari ve donusturmeler.

Saf fonksiyonlar: DB'den veri ceker, dict olarak dondurur.
Side effect yok. Bos DB'de graceful varsayilanlar.
"""

import math
from datetime import datetime, timedelta

from src.database import get_db
from src.learner.beta_model import BetaPosterior
from src.learner.metrics import CHANNELS

ALERT_LABELS = {0: "Normal", 1: "Dikkat", 2: "Uyarı", 3: "Acil"}


def get_status_data(db_path: str, mqtt_connected: bool) -> dict:
    """Anlik durum verisi.

    Son event, bugunun event sayisi, ogrenme durumu, alarm seviyesi.

    Args:
        db_path: SQLite veritabani yolu
        mqtt_connected: MQTT baglanti durumu

    Returns:
        Status dict (her zaman gecerli, bos DB'de varsayilanlar)
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    with get_db(db_path) as conn:
        # Son event
        row = conn.execute(
            "SELECT timestamp, sensor_id, channel FROM sensor_events "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        if row:
            last_event = {
                "timestamp": row["timestamp"],
                "sensor_id": row["sensor_id"],
                "channel": row["channel"],
            }
            # age_minutes hesapla
            try:
                event_dt = datetime.fromisoformat(row["timestamp"])
                age = (now - event_dt).total_seconds() / 60.0
                last_event["age_minutes"] = round(age, 1)
            except (ValueError, TypeError):
                last_event["age_minutes"] = None
        else:
            last_event = None

        # Bugunun event sayisi
        count_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM sensor_events WHERE timestamp >= ?",
            (today,),
        ).fetchone()
        today_event_count = count_row["cnt"] if count_row else 0

        # Ogrenme durumu - en son daily_scores
        score_row = conn.execute(
            "SELECT train_days, is_learning, composite_z, alert_level "
            "FROM daily_scores ORDER BY date DESC LIMIT 1"
        ).fetchone()

        if score_row:
            train_days = score_row["train_days"] or 0
            is_learning = bool(score_row["is_learning"])
            composite_z = score_row["composite_z"]
            alert_level = score_row["alert_level"] or 0
        else:
            train_days = 0
            is_learning = True
            composite_z = 0.0
            alert_level = 0

        # Toplam gun sayisi
        days_row = conn.execute(
            "SELECT COUNT(DISTINCT date) as cnt FROM daily_scores"
        ).fetchone()
        total_days = days_row["cnt"] if days_row else 0

        # avg_ci_width - model_state'ten anlik hesapla
        avg_ci_width = _compute_avg_ci_width(conn)

    return {
        "last_event": last_event,
        "today_event_count": today_event_count,
        "learning": {
            "is_learning": is_learning,
            "train_days": train_days,
            "total_days": total_days,
            "avg_ci_width": round(avg_ci_width, 4),
        },
        "alert": {
            "level": alert_level,
            "label": ALERT_LABELS.get(alert_level, "Bilinmeyen"),
            "composite_z": round(composite_z, 2) if composite_z else 0.0,
        },
        "mqtt_connected": mqtt_connected,
    }


def get_daily_data(db_path: str, date: str, channels: list[str] | None = None) -> dict | None:
    """Belirli bir gune ait detayli veri.

    Args:
        db_path: SQLite veritabani yolu
        date: YYYY-MM-DD formatinda tarih
        channels: Kanal listesi (None ise CHANNELS default)

    Returns:
        Daily data dict veya None (tarih bulunamazsa)
    """
    ch_list = channels if channels is not None else list(CHANNELS)
    with get_db(db_path) as conn:
        # daily_scores
        score_row = conn.execute(
            "SELECT * FROM daily_scores WHERE date = ?", (date,)
        ).fetchone()

        if score_row is None:
            return None

        scores = dict(score_row)

        # slot_summary -> kanal bazli 96 slot array
        slots = {ch: [0] * 96 for ch in ch_list}
        event_counts = {ch: 0 for ch in ch_list}

        slot_rows = conn.execute(
            "SELECT slot, channel, active, event_count "
            "FROM slot_summary WHERE date = ?",
            (date,),
        ).fetchall()

        for row in slot_rows:
            ch = row["channel"]
            s = row["slot"]
            if ch in slots and 0 <= s < 96:
                slots[ch][s] = row["active"]
                event_counts[ch] += row["event_count"]

    return {
        "date": date,
        "scores": scores,
        "slots": slots,
        "event_counts": event_counts,
    }


def get_history_data(db_path: str, days: int = 30) -> dict:
    """Tarihsel gunluk skor verileri.

    Args:
        db_path: SQLite veritabani yolu
        days: Kac gunluk veri (varsayilan 30)

    Returns:
        History dict (bos DB'de bos liste)
    """
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT date, nll_total, composite_z, alert_level, "
            "observed_count, is_learning, train_days "
            "FROM daily_scores ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()

    return {
        "days": [
            {
                "date": row["date"],
                "nll_total": row["nll_total"],
                "composite_z": row["composite_z"],
                "alert_level": row["alert_level"],
                "observed_count": row["observed_count"],
                "is_learning": bool(row["is_learning"]),
                "train_days": row["train_days"],
            }
            for row in rows
        ]
    }


def get_heatmap_data(db_path: str, channels: list[str] | None = None) -> dict:
    """Model olasilik haritasi ve son 14 gunun gercek aktivitesi.

    Args:
        db_path: SQLite veritabani yolu
        channels: Kanal listesi (None ise CHANNELS default)

    Returns:
        Heatmap dict: model (96 slot x N kanal) + recent_activity
    """
    ch_list = channels if channels is not None else list(CHANNELS)
    default_prior = BetaPosterior(1.0, 1.0)

    with get_db(db_path) as conn:
        # Bulk SELECT 1: tum model_state satirlarini tek sorguda al
        model_rows = conn.execute(
            "SELECT slot, channel, alpha, beta FROM model_state"
        ).fetchall()

        # Dict lookup: {(slot, channel): (alpha, beta)}
        model_lookup: dict[tuple[int, str], tuple[float, float]] = {}
        for row in model_rows:
            model_lookup[(row["slot"], row["channel"])] = (
                row["alpha"], row["beta"]
            )

        # Model olasilik haritasi olustur
        model = {}
        for ch in ch_list:
            channel_data = []
            for s in range(96):
                ab = model_lookup.get((s, ch))
                if ab:
                    bp = BetaPosterior(ab[0], ab[1])
                else:
                    bp = default_prior
                channel_data.append({
                    "slot": s,
                    "probability": round(bp.mean, 4),
                    "ci_width": round(bp.ci_width, 4),
                })
            model[ch] = channel_data

        # Bulk SELECT 2: son 14 gunun ortalama aktivitesi (tek sorgu)
        cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        activity_rows = conn.execute(
            "SELECT channel, slot, AVG(active) as avg_active "
            "FROM slot_summary "
            "WHERE date >= ? "
            "GROUP BY channel, slot",
            (cutoff,),
        ).fetchall()

        # Dict lookup: {(channel, slot): avg_active}
        activity_lookup: dict[tuple[str, int], float] = {}
        for row in activity_rows:
            activity_lookup[(row["channel"], row["slot"])] = row["avg_active"]

        recent_activity = {}
        for ch in ch_list:
            recent_activity[ch] = [
                round(activity_lookup.get((ch, s), 0.0), 4)
                for s in range(96)
            ]

    return {
        "model": model,
        "recent_activity": recent_activity,
    }


def get_learning_curve_data(db_path: str) -> dict:
    """Ogrenme egrisi verileri.

    Args:
        db_path: SQLite veritabani yolu

    Returns:
        Learning curve dict (paralel arrayler)
    """
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT date, train_days, nll_total, "
            "aw_accuracy, aw_balanced_acc "
            "FROM daily_scores ORDER BY date ASC"
        ).fetchall()

    dates = []
    train_days_list = []
    nll_totals = []
    accuracies = []
    balanced_accuracies = []
    ci_widths = []

    for row in rows:
        dates.append(row["date"])
        td = row["train_days"] or 0
        train_days_list.append(td)
        nll_totals.append(row["nll_total"])
        accuracies.append(row["aw_accuracy"])
        balanced_accuracies.append(row["aw_balanced_acc"])
        # avg_ci_width DB'de yok -> yaklasim formuluyle hesapla
        # 90% CI: z=1.645, 4 kanal * 96 slot, Beta(1 + n_active, 1 + n_inactive)
        # Ortalama yaklasim: 1.645 * 2 / sqrt(4 * (2 + train_days))
        ci = _approximate_ci_width(td)
        ci_widths.append(round(ci, 4))

    return {
        "dates": dates,
        "train_days": train_days_list,
        "nll_totals": nll_totals,
        "accuracies": accuracies,
        "balanced_accuracies": balanced_accuracies,
        "ci_widths": ci_widths,
    }


def _compute_avg_ci_width(conn) -> float:
    """Model state'ten anlik ortalama CI genisligi hesapla.

    Args:
        conn: Acik SQLite baglantisi

    Returns:
        Ortalama CI genisligi (model yoksa 1.0)
    """
    rows = conn.execute(
        "SELECT alpha, beta FROM model_state"
    ).fetchall()

    if not rows:
        return 1.0

    widths = [BetaPosterior(r["alpha"], r["beta"]).ci_width for r in rows]
    return sum(widths) / len(widths)


def _approximate_ci_width(train_days: int) -> float:
    """Tarihsel CI genisligi yaklasimi.

    Beta(1, 1) prior ile n gozlem sonrasi ortalama CI genisligi.
    Formul: 2 * z * sigma, sigma = sqrt(p*(1-p) / (alpha+beta+1))
    Yaklasim: 1.645 * 2 / sqrt(4 * (2 + train_days))

    Args:
        train_days: Egitim gun sayisi

    Returns:
        Yaklasik CI genisligi
    """
    if train_days <= 0:
        return 1.0
    return 1.645 * 2 / math.sqrt(4 * (2 + train_days))
