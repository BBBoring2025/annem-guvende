"""Dashboard API endpoint testleri."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.dashboard.api import router as dashboard_router
from src.database import get_db


def _create_test_app(db_path: str) -> FastAPI:
    """Test icin minimal FastAPI app olustur."""
    app = FastAPI()
    app.include_router(dashboard_router)

    # Mock app.state
    app.state.db_path = db_path
    app.state.mqtt_collector = MagicMock(
        is_connected=MagicMock(return_value=False)
    )

    return app


def _insert_daily_score(conn, date, **kwargs):
    """Test icin daily_scores'a kayit ekle."""
    defaults = dict(
        train_days=10,
        nll_presence=5.0, nll_fridge=3.0, nll_bathroom=4.0, nll_door=2.0,
        nll_total=14.0, expected_count=50.0, observed_count=45,
        count_z=-0.5, composite_z=1.2, alert_level=0,
        aw_accuracy=0.75, aw_balanced_acc=0.72, aw_active_recall=0.68,
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
            defaults["train_days"], defaults["nll_presence"], defaults["nll_fridge"],
            defaults["nll_bathroom"], defaults["nll_door"], defaults["nll_total"],
            defaults["expected_count"], defaults["observed_count"], defaults["count_z"],
            defaults["composite_z"], defaults["alert_level"], defaults["aw_accuracy"],
            defaults["aw_balanced_acc"], defaults["aw_active_recall"], defaults["is_learning"],
        ),
    )
    conn.commit()


# --- Endpoint testleri ---

def test_api_status_empty(initialized_db):
    """Bos DB'de /api/status 200 donmeli."""
    app = _create_test_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/api/status")
    assert resp.status_code == 200

    data = resp.json()
    assert data["last_event"] is None
    assert data["today_event_count"] == 0
    assert "learning" in data
    assert "alert" in data
    assert data["mqtt_connected"] is False


def test_api_status_with_mqtt(initialized_db):
    """MQTT connected=True dogrulamasi."""
    app = _create_test_app(initialized_db)
    app.state.mqtt_collector.is_connected.return_value = True
    client = TestClient(app)

    resp = client.get("/api/status")
    data = resp.json()
    assert data["mqtt_connected"] is True


def test_api_daily_existing(initialized_db):
    """/api/daily/{date} mevcut tarih icin 200 donmeli."""
    date = "2025-02-01"
    with get_db(initialized_db) as conn:
        _insert_daily_score(conn, date, train_days=8, nll_total=12.0)

    app = _create_test_app(initialized_db)
    client = TestClient(app)

    resp = client.get(f"/api/daily/{date}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["date"] == date
    assert "scores" in data
    assert "slots" in data
    assert "event_counts" in data


def test_api_daily_not_found(initialized_db):
    """/api/daily/{date} olmayan tarih icin 404 donmeli."""
    app = _create_test_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/api/daily/2099-12-31")
    assert resp.status_code == 404


def test_api_history(initialized_db):
    """/api/history JSON yapisini dogrula."""
    with get_db(initialized_db) as conn:
        for i in range(3):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            _insert_daily_score(conn, date, train_days=10 + i)

    app = _create_test_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/api/history?days=10")
    assert resp.status_code == 200

    data = resp.json()
    assert "days" in data
    assert len(data["days"]) == 3


def test_api_heatmap(initialized_db):
    """/api/heatmap JSON yapisini dogrula."""
    app = _create_test_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/api/heatmap")
    assert resp.status_code == 200

    data = resp.json()
    assert "model" in data
    assert "recent_activity" in data
    assert set(data["model"].keys()) == {"presence", "fridge", "bathroom", "door"}


def test_api_learning_curve(initialized_db):
    """/api/learning-curve JSON yapisini dogrula."""
    app = _create_test_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/api/learning-curve")
    assert resp.status_code == 200

    data = resp.json()
    assert "dates" in data
    assert "train_days" in data
    assert "nll_totals" in data
    assert "ci_widths" in data


def test_api_health(initialized_db):
    """/api/health 200 ve status alani donmeli."""
    app = _create_test_app(initialized_db)
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 200

    data = resp.json()
    assert "status" in data
