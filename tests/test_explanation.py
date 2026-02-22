"""Anomali aciklama uretimi testleri."""

import httpx
import pytest

from src.alerter.alert_manager import AlertManager
from src.alerter.telegram_bot import TelegramNotifier
from src.config import AppConfig
from src.database import get_db, init_db


class MockTransport(httpx.BaseTransport):
    def handle_request(self, request):
        return httpx.Response(200, json={"ok": True})


def _make_manager() -> AlertManager:
    """Test icin AlertManager olustur."""
    client = httpx.Client(transport=MockTransport())
    notifier = TelegramNotifier("test_token", ["111"], client=client)
    config = AppConfig(
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
    )
    return AlertManager(config, notifier)


def _insert_daily_score(
    db_path: str, date: str, *,
    nll_total: float = 50.0,
    nll_presence: float = 12.0,
    nll_fridge: float = 12.0,
    nll_bathroom: float = 12.0,
    nll_door: float = 12.0,
    count_z: float = 0.0,
    observed_count: int = 100,
    expected_count: float = 100.0,
    alert_level: int = 0,
    is_learning: int = 0,
    train_days: int = 15,
    composite_z: float = 0.5,
):
    """Test icin daily_scores satiri ekle."""
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_scores
            (date, train_days, nll_total, nll_presence, nll_fridge,
             nll_bathroom, nll_door, count_z, observed_count,
             expected_count, alert_level, is_learning, composite_z,
             aw_accuracy, aw_balanced_acc, aw_active_recall)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    0.8, 0.8, 0.8)""",
            (date, train_days, nll_total, nll_presence, nll_fridge,
             nll_bathroom, nll_door, count_z, observed_count,
             expected_count, alert_level, is_learning, composite_z),
        )
        conn.commit()


@pytest.fixture
def explain_db(tmp_path):
    """Aciklama testleri icin hazir DB."""
    db_path = str(tmp_path / "explain_test.db")
    init_db(db_path)
    return db_path


def test_low_fridge_nll_explanation(explain_db):
    """Dusuk buzdolabi NLL (1.5x ortalama) -> 'Buzdolabı' iceriyor."""
    manager = _make_manager()

    # 5 normal gun tarihce
    for i in range(5):
        _insert_daily_score(
            explain_db, f"2025-01-{i + 1:02d}",
            nll_fridge=10.0,  # normal
        )

    # Anomali gunu: buzdolabi NLL cok yuksek (10.0 * 2 = 20.0 > 1.5x)
    _insert_daily_score(
        explain_db, "2025-02-01",
        nll_fridge=20.0,  # 2x ortalama
        alert_level=1,
    )

    result = manager.generate_explanation(explain_db, "2025-02-01")

    assert "Buzdolabı" in result


def test_low_count_z_explanation(explain_db):
    """Dusuk count_z -> 'düşük' ve observed/expected iceriyor."""
    manager = _make_manager()

    for i in range(5):
        _insert_daily_score(explain_db, f"2025-01-{i + 1:02d}")

    _insert_daily_score(
        explain_db, "2025-02-01",
        count_z=-3.0,
        observed_count=20,
        expected_count=100.0,
        alert_level=1,
    )

    result = manager.generate_explanation(explain_db, "2025-02-01")

    assert "düşük" in result
    assert "20" in result
    assert "100" in result


def test_multiple_anomal_channels(explain_db):
    """Birden fazla anomal kanal -> hepsi aciklamada."""
    manager = _make_manager()

    for i in range(5):
        _insert_daily_score(
            explain_db, f"2025-01-{i + 1:02d}",
            nll_presence=10.0,
            nll_bathroom=10.0,
        )

    _insert_daily_score(
        explain_db, "2025-02-01",
        nll_presence=20.0,  # 2x
        nll_bathroom=18.0,  # 1.8x
        alert_level=2,
    )

    result = manager.generate_explanation(explain_db, "2025-02-01")

    assert "Hareket" in result
    assert "Banyo" in result


def test_insufficient_history(explain_db):
    """Tarihce yetersiz (< 3 gun) -> basit aciklama."""
    manager = _make_manager()

    # Sadece 2 normal gun
    _insert_daily_score(explain_db, "2025-01-01")
    _insert_daily_score(explain_db, "2025-01-02")

    # Anomali gunu (tarihce yetersiz: 2 normal gun, hedef haric edilince)
    _insert_daily_score(
        explain_db, "2025-02-01",
        nll_fridge=20.0, alert_level=1,
    )

    result = manager.generate_explanation(explain_db, "2025-02-01")

    assert "yeterli" in result.lower() or "veri" in result.lower()


def test_no_data_explanation(explain_db):
    """Veri yok -> 'Detaylı bilgi mevcut değil'."""
    manager = _make_manager()

    result = manager.generate_explanation(explain_db, "2099-01-01")

    assert "Detaylı bilgi mevcut değil" in result
