"""Dashboard charts veri katmani testleri."""

from datetime import datetime, timedelta

from src.dashboard.charts import (
    _approximate_ci_width,
    get_daily_data,
    get_heatmap_data,
    get_history_data,
    get_learning_curve_data,
    get_status_data,
)
from src.database import get_db

# --- Yardimci fonksiyonlar ---

def _insert_event(conn, timestamp, sensor_id="mutfak_motion", channel="presence"):
    """Test icin sensor_events'e kayit ekle."""
    conn.execute(
        "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type) "
        "VALUES (?, ?, ?, 'state_change')",
        (timestamp, sensor_id, channel),
    )
    conn.commit()


def _insert_daily_score(conn, date, **kwargs):
    """Test icin daily_scores'a kayit ekle."""
    defaults = dict(
        train_days=10,
        nll_presence=5.0,
        nll_fridge=3.0,
        nll_bathroom=4.0,
        nll_door=2.0,
        nll_total=14.0,
        expected_count=50.0,
        observed_count=45,
        count_z=-0.5,
        composite_z=1.2,
        alert_level=0,
        aw_accuracy=0.75,
        aw_balanced_acc=0.72,
        aw_active_recall=0.68,
        is_learning=1,
    )
    defaults.update(kwargs)
    conn.execute(
        "INSERT INTO daily_scores "
        "(date, train_days, nll_presence, nll_fridge, nll_bathroom, nll_door, "
        "nll_total, expected_count, observed_count, count_z, composite_z, "
        "alert_level, aw_accuracy, aw_balanced_acc, aw_active_recall, is_learning) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            date,
            defaults["train_days"],
            defaults["nll_presence"],
            defaults["nll_fridge"],
            defaults["nll_bathroom"],
            defaults["nll_door"],
            defaults["nll_total"],
            defaults["expected_count"],
            defaults["observed_count"],
            defaults["count_z"],
            defaults["composite_z"],
            defaults["alert_level"],
            defaults["aw_accuracy"],
            defaults["aw_balanced_acc"],
            defaults["aw_active_recall"],
            defaults["is_learning"],
        ),
    )
    conn.commit()


def _insert_slot_summary(conn, date, slot, channel, active=1, event_count=1):
    """Test icin slot_summary'ye kayit ekle."""
    conn.execute(
        "INSERT INTO slot_summary (date, slot, channel, active, event_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (date, slot, channel, active, event_count),
    )
    conn.commit()


def _insert_model_state(conn, slot, channel, alpha=5.0, beta=3.0):
    """Test icin model_state'e kayit ekle."""
    conn.execute(
        "INSERT OR REPLACE INTO model_state (slot, channel, alpha, beta, last_updated) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (slot, channel, alpha, beta),
    )
    conn.commit()


# --- get_status_data testleri ---

def test_get_status_data_empty_db(initialized_db):
    """Bos DB'de varsayilan degerler donmeli."""
    result = get_status_data(initialized_db, mqtt_connected=False)

    assert result["last_event"] is None
    assert result["today_event_count"] == 0
    assert result["learning"]["is_learning"] is True
    assert result["learning"]["train_days"] == 0
    assert result["learning"]["total_days"] == 0
    assert result["alert"]["level"] == 0
    assert result["alert"]["label"] == "Normal"
    assert result["mqtt_connected"] is False


def test_get_status_data_with_data(initialized_db):
    """Verili DB'de dogru degerler donmeli."""
    now = datetime.now()
    ts = now.strftime("%Y-%m-%dT%H:%M:%S")

    with get_db(initialized_db) as conn:
        _insert_event(conn, ts, "buzdolabi", "fridge")
        _insert_daily_score(conn, now.strftime("%Y-%m-%d"),
                            train_days=12, alert_level=1,
                            composite_z=2.5, is_learning=0)

    result = get_status_data(initialized_db, mqtt_connected=True)

    assert result["last_event"] is not None
    assert result["last_event"]["channel"] == "fridge"
    assert result["today_event_count"] == 1
    assert result["learning"]["train_days"] == 12
    assert result["learning"]["is_learning"] is False
    assert result["learning"]["total_days"] == 1
    assert result["alert"]["level"] == 1
    assert result["alert"]["label"] == "Dikkat"
    assert result["alert"]["composite_z"] == 2.5
    assert result["mqtt_connected"] is True


# --- get_daily_data testleri ---

def test_get_daily_data_existing(initialized_db):
    """Mevcut tarih icin scores + slots donmeli."""
    date = "2025-02-01"
    with get_db(initialized_db) as conn:
        _insert_daily_score(conn, date, train_days=8, nll_total=12.0)
        _insert_slot_summary(conn, date, 0, "presence", active=1, event_count=3)
        _insert_slot_summary(conn, date, 1, "fridge", active=0, event_count=0)

    result = get_daily_data(initialized_db, date)

    assert result is not None
    assert result["date"] == date
    assert result["scores"]["train_days"] == 8
    assert result["scores"]["nll_total"] == 12.0
    assert result["slots"]["presence"][0] == 1
    assert result["slots"]["fridge"][1] == 0
    assert result["event_counts"]["presence"] == 3


def test_get_daily_data_missing(initialized_db):
    """Olmayan tarih icin None donmeli."""
    result = get_daily_data(initialized_db, "2099-01-01")
    assert result is None


# --- get_history_data testleri ---

def test_get_history_data(initialized_db):
    """N gün tarih sıralı dönmeli."""
    with get_db(initialized_db) as conn:
        for i in range(5):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            _insert_daily_score(conn, date, train_days=10 + i)

    result = get_history_data(initialized_db, days=30)

    assert len(result["days"]) == 5
    # DESC sirayla
    assert result["days"][0]["date"] >= result["days"][-1]["date"]
    # Her kayit gerekli alanlara sahip
    for day in result["days"]:
        assert "date" in day
        assert "nll_total" in day
        assert "composite_z" in day
        assert "alert_level" in day
        assert "is_learning" in day


def test_get_history_respects_days(initialized_db):
    """days parametresi max kayit sayisini sinirlamali."""
    with get_db(initialized_db) as conn:
        for i in range(10):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            _insert_daily_score(conn, date, train_days=i)

    result = get_history_data(initialized_db, days=5)
    assert len(result["days"]) == 5


# --- get_heatmap_data testleri ---

def test_get_heatmap_data(initialized_db):
    """Model + recent_activity 96 slot x 4 kanal olmali."""
    with get_db(initialized_db) as conn:
        # Birkac model state ekle
        _insert_model_state(conn, 0, "presence", alpha=10.0, beta=2.0)
        _insert_model_state(conn, 24, "fridge", alpha=3.0, beta=8.0)
        # Birkac recent slot
        date = datetime.now().strftime("%Y-%m-%d")
        _insert_slot_summary(conn, date, 0, "presence", active=1)

    result = get_heatmap_data(initialized_db)

    # 4 kanal model var
    assert set(result["model"].keys()) == {"presence", "fridge", "bathroom", "door"}
    # Her kanal 96 slot
    for ch in result["model"]:
        assert len(result["model"][ch]) == 96
        # Her slot'ta probability ve ci_width
        for slot_data in result["model"][ch]:
            assert "slot" in slot_data
            assert 0.0 <= slot_data["probability"] <= 1.0
            assert slot_data["ci_width"] >= 0.0

    # recent_activity
    assert set(result["recent_activity"].keys()) == {"presence", "fridge", "bathroom", "door"}
    for ch in result["recent_activity"]:
        assert len(result["recent_activity"][ch]) == 96

    # Ozel model state -> probability yuksek olmali
    presence_slot0 = result["model"]["presence"][0]
    assert presence_slot0["probability"] > 0.7  # alpha=10, beta=2 -> ~0.83


# --- get_learning_curve_data testleri ---

def test_get_learning_curve_data(initialized_db):
    """Paralel arrayler esit uzunlukta olmali."""
    with get_db(initialized_db) as conn:
        for i in range(7):
            date = (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%d")
            _insert_daily_score(conn, date, train_days=i + 1)

    result = get_learning_curve_data(initialized_db)

    n = len(result["dates"])
    assert n == 7
    assert len(result["train_days"]) == n
    assert len(result["nll_totals"]) == n
    assert len(result["accuracies"]) == n
    assert len(result["balanced_accuracies"]) == n
    assert len(result["ci_widths"]) == n

    # train_days artan sirayla
    assert result["train_days"] == sorted(result["train_days"])

    # ci_widths pozitif
    for ci in result["ci_widths"]:
        assert ci > 0


def test_get_learning_curve_data_empty(initialized_db):
    """Bos DB'de bos arrayler donmeli."""
    result = get_learning_curve_data(initialized_db)

    assert result["dates"] == []
    assert result["train_days"] == []
    assert result["nll_totals"] == []
    assert result["ci_widths"] == []


# --- _approximate_ci_width testleri ---

def test_approximate_ci_width_decreases():
    """Daha fazla egitim gunu -> daha dar CI."""
    w1 = _approximate_ci_width(1)
    w7 = _approximate_ci_width(7)
    w14 = _approximate_ci_width(14)
    w30 = _approximate_ci_width(30)

    assert w1 > w7 > w14 > w30

    # train_days=0 -> 1.0
    assert _approximate_ci_width(0) == 1.0
