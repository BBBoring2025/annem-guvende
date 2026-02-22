"""Kirilganlik endeksi (trend analizi) testleri — Sprint 14."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config import AppConfig
from src.dashboard.api import router as dashboard_router
from src.database import get_db, init_db
from src.detector.trend_analyzer import (
    analyze_all_trends,
    calculate_channel_trend,
    get_daily_event_counts,
    linear_regression_slope,
)

# --- Lineer Regresyon Testleri ---


def test_linear_regression_slope_positive():
    """Artan seri → pozitif egim (~1.0)."""
    slope = linear_regression_slope([1.0, 2.0, 3.0, 4.0, 5.0])
    assert slope > 0
    assert abs(slope - 1.0) < 0.01


def test_linear_regression_slope_negative():
    """Azalan seri → negatif egim (~-1.0)."""
    slope = linear_regression_slope([5.0, 4.0, 3.0, 2.0, 1.0])
    assert slope < 0
    assert abs(slope - (-1.0)) < 0.01


def test_linear_regression_slope_flat():
    """Sabit seri → egim ~0.0."""
    slope = linear_regression_slope([3.0, 3.0, 3.0, 3.0])
    assert abs(slope) < 0.01


def test_linear_regression_slope_single_value():
    """Tek deger → 0.0 donmeli."""
    slope = linear_regression_slope([5.0])
    assert slope == 0.0


# --- Kanal Trend Testleri ---


def _insert_events(db_path: str, channel: str, date_str: str, count: int):
    """Belirli bir gune belirli sayida event ekle."""
    with get_db(db_path) as conn:
        for i in range(count):
            ts = f"{date_str}T{10 + i % 12:02d}:00:00"
            conn.execute(
                "INSERT INTO sensor_events "
                "(timestamp, sensor_id, channel, event_type, value) "
                "VALUES (?, ?, ?, 'state_change', 'on')",
                (ts, f"{channel}_sensor", channel),
            )
        conn.commit()


def test_calculate_channel_trend_insufficient_data(tmp_path):
    """5 gunluk veri, min_days=14 → None donmeli."""
    db_path = str(tmp_path / "trend_test.db")
    init_db(db_path)

    now = datetime(2025, 3, 20, 12, 0)
    result = calculate_channel_trend(db_path, "presence", days=5, min_days=14, now=now)
    assert result is None


def test_calculate_channel_trend_with_enough_data(tmp_path):
    """20 gunluk artan veri → float slope donmeli."""
    db_path = str(tmp_path / "trend_test.db")
    init_db(db_path)

    now = datetime(2025, 3, 20, 23, 0)
    for i in range(20):
        d = (now - timedelta(days=19 - i)).strftime("%Y-%m-%d")
        _insert_events(db_path, "bathroom", d, count=i + 1)

    result = calculate_channel_trend(
        db_path, "bathroom", days=20, min_days=14, now=now,
    )
    assert result is not None
    assert isinstance(result, float)
    assert result > 0  # artan seri


def test_analyze_all_trends_returns_dict(tmp_path):
    """2 kanal → dict[str, float|None] donmeli."""
    db_path = str(tmp_path / "trend_test.db")
    init_db(db_path)

    now = datetime(2025, 3, 20, 23, 0)
    for i in range(20):
        d = (now - timedelta(days=19 - i)).strftime("%Y-%m-%d")
        _insert_events(db_path, "presence", d, count=5)

    result = analyze_all_trends(
        db_path, ["presence", "bathroom"], days=20, min_days=14, now=now,
    )
    assert isinstance(result, dict)
    assert "presence" in result
    assert "bathroom" in result
    assert isinstance(result["presence"], float)


# --- API Endpoint Testi ---


def _create_test_app_with_config(db_path: str) -> FastAPI:
    """Trend testi icin FastAPI app (config mock dahil)."""
    app = FastAPI()
    app.include_router(dashboard_router)
    app.state.db_path = db_path
    app.state.config = AppConfig()
    app.state.mqtt_collector = MagicMock(
        is_connected=MagicMock(return_value=False)
    )
    return app


def test_trends_api_endpoint(tmp_path):
    """/api/trends → 200 + trends dict + period_days donmeli."""
    db_path = str(tmp_path / "trend_api.db")
    init_db(db_path)

    app = _create_test_app_with_config(db_path)
    client = TestClient(app)

    resp = client.get("/api/trends")
    assert resp.status_code == 200

    data = resp.json()
    assert "trends" in data
    assert "period_days" in data
    assert isinstance(data["trends"], dict)
    assert data["period_days"] == 30  # default


# --- Sifir-Gun Doldurma Testi ---


def test_trend_fills_zero_event_days(tmp_path):
    """Sadece 1., 5., 10. gunlere event yaz → tam 10 eleman, bos gunler 0."""
    db_path = str(tmp_path / "fill_test.db")
    init_db(db_path)

    now = datetime(2025, 3, 20, 23, 0)
    # 10 gunluk pencere: 11 Mart - 20 Mart
    day_1 = (now - timedelta(days=9)).strftime("%Y-%m-%d")   # 11 Mart
    day_5 = (now - timedelta(days=5)).strftime("%Y-%m-%d")   # 15 Mart
    day_10 = now.strftime("%Y-%m-%d")                        # 20 Mart

    _insert_events(db_path, "presence", day_1, count=3)
    _insert_events(db_path, "presence", day_5, count=5)
    _insert_events(db_path, "presence", day_10, count=2)

    daily = get_daily_event_counts(db_path, "presence", days=10, now=now)

    # Tam 10 eleman olmali
    assert len(daily) == 10

    # Kronolojik sira kontrolu
    dates = [d for d, _ in daily]
    assert dates == sorted(dates)

    # Bos gunler 0 olmali
    count_map = dict(daily)
    assert count_map[day_1] == 3
    assert count_map[day_5] == 5
    assert count_map[day_10] == 2

    # Aradaki gunler 0 olmali
    zero_days = [d for d, c in daily if c == 0]
    assert len(zero_days) == 7  # 10 - 3 = 7 bos gun
