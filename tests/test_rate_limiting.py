"""Rate limiting testleri - AlertManager karar motoru."""

from datetime import datetime, timedelta

import httpx

from src.alerter.alert_manager import AlertManager
from src.alerter.telegram_bot import TelegramNotifier
from src.config import AppConfig
from src.database import get_system_state, init_db
from src.detector.realtime_checks import RealtimeAlert


class MockTransport(httpx.BaseTransport):
    """Deterministik mock transport."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def handle_request(self, request):
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})


def _make_manager() -> tuple[AlertManager, MockTransport]:
    """Test icin AlertManager + mock notifier olustur."""
    mock = MockTransport()
    client = httpx.Client(transport=mock)
    notifier = TelegramNotifier("test_token", ["111"], client=client)
    config = AppConfig(
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
    )
    manager = AlertManager(config, notifier)
    return manager, mock


# --- should_send_alert testleri ---

def test_first_alert_sends():
    """Ilk alarm -> gonderilir (True)."""
    manager, _ = _make_manager()
    now = datetime(2025, 3, 1, 14, 0)

    assert manager.should_send_alert(alert_level=1, train_days=15, now=now) is True


def test_same_level_cooldown():
    """Ayni seviye 6 saat icinde -> gonderilmez (False)."""
    manager, _ = _make_manager()
    t1 = datetime(2025, 3, 1, 14, 0)
    t2 = t1 + timedelta(hours=3)  # 3 saat sonra

    manager.should_send_alert(alert_level=1, train_days=15, now=t1)
    assert manager.should_send_alert(alert_level=1, train_days=15, now=t2) is False


def test_cooldown_expired():
    """6 saat sonrasi -> gonderilir (True)."""
    manager, _ = _make_manager()
    t1 = datetime(2025, 3, 1, 14, 0)
    t2 = t1 + timedelta(hours=7)  # 7 saat sonra

    manager.should_send_alert(alert_level=1, train_days=15, now=t1)
    assert manager.should_send_alert(alert_level=1, train_days=15, now=t2) is True


def test_level_escalation_bypasses_cooldown():
    """Seviye yukselmesi (1->2) -> her zaman gonderilir."""
    manager, _ = _make_manager()
    t1 = datetime(2025, 3, 1, 14, 0)
    t2 = t1 + timedelta(minutes=30)  # 30dk sonra

    manager.should_send_alert(alert_level=1, train_days=15, now=t1)
    # Level 2'ye yukselme -> cooldown gecerli degil
    assert manager.should_send_alert(alert_level=2, train_days=15, now=t2) is True


def test_learning_days_1_to_7_no_alert():
    """Gun 1-7: alarm gonderilmez."""
    manager, _ = _make_manager()
    now = datetime(2025, 3, 1, 14, 0)

    assert manager.should_send_alert(alert_level=1, train_days=3, now=now) is False
    assert manager.should_send_alert(alert_level=2, train_days=5, now=now) is False
    assert manager.should_send_alert(alert_level=3, train_days=6, now=now) is False


def test_learning_days_8_to_14_max_level_1():
    """Gun 8-14: max level 1, level 2+ gonderilmez."""
    manager, _ = _make_manager()
    now = datetime(2025, 3, 1, 14, 0)

    assert manager.should_send_alert(alert_level=1, train_days=10, now=now) is True
    assert manager.should_send_alert(alert_level=2, train_days=10, now=now) is False
    assert manager.should_send_alert(alert_level=3, train_days=12, now=now) is False


def test_learning_days_15_plus_all_levels():
    """Gun 15+: tum seviyeler aktif."""
    manager, _ = _make_manager()
    t1 = datetime(2025, 3, 1, 14, 0)
    t2 = t1 + timedelta(hours=7)
    t3 = t2 + timedelta(hours=7)

    assert manager.should_send_alert(alert_level=1, train_days=15, now=t1) is True
    assert manager.should_send_alert(alert_level=2, train_days=15, now=t2) is True
    assert manager.should_send_alert(alert_level=3, train_days=20, now=t3) is True


# --- should_send_morning testleri ---

def test_morning_alert_limit():
    """Sabah alarm limiti: gunluk max 2."""
    manager, _ = _make_manager()
    date = "2025-03-01"

    assert manager.should_send_morning(date) is True
    assert manager.should_send_morning(date) is True
    assert manager.should_send_morning(date) is False  # 3. kez -> engellenir


def test_morning_alert_different_day():
    """Farkli gunler: her gun icin bagimsiz sayac."""
    manager, _ = _make_manager()

    assert manager.should_send_morning("2025-03-01") is True
    assert manager.should_send_morning("2025-03-01") is True
    assert manager.should_send_morning("2025-03-01") is False
    # Yeni gun -> sifirdan baslar
    assert manager.should_send_morning("2025-03-02") is True


# --- DB persist testleri ---

def test_rate_limit_persists_to_db(tmp_path):
    """db_path ile alert -> state DB'ye yazilir."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    manager, _ = _make_manager()
    now = datetime(2025, 3, 1, 14, 0)

    manager.should_send_alert(alert_level=1, train_days=15, now=now, db_path=db_path)

    # DB'de kayit olmali
    raw = get_system_state(db_path, "alert_rate_state", "")
    assert "1:" in raw
    assert "2025-03-01" in raw


def test_rate_limit_loads_from_db(tmp_path):
    """Yeni AlertManager instance DB'deki cooldown'i taniyor."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    # Ilk manager: alert gonder (DB'ye yazilir)
    manager1, _ = _make_manager()
    t1 = datetime(2025, 3, 1, 14, 0)
    assert manager1.should_send_alert(alert_level=1, train_days=15, now=t1, db_path=db_path) is True

    # Yeni manager (bos RAM cache, ama DB'den yukleyecek)
    manager2, _ = _make_manager()
    t2 = t1 + timedelta(hours=3)  # 3 saat sonra — cooldown icinde
    assert manager2.should_send_alert(alert_level=1, train_days=15, now=t2, db_path=db_path) is False


# --- Realtime alert DB persist testleri ---

def test_handle_realtime_alert_persists_to_db(tmp_path):
    """handle_realtime_alert(db_path=...) -> extended_silence rate state DB'ye yazilir."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    manager, mock = _make_manager()
    alert = RealtimeAlert(
        alert_type="extended_silence",
        alert_level=1,
        message="3.5 saattir aktivite yok.",
        last_event_time="2025-03-01T09:00:00",
    )
    manager.handle_realtime_alert(alert, db_path=db_path)
    raw = get_system_state(db_path, "alert_rate_state", "")
    assert "1:" in raw
    assert len(mock.requests) == 1


def test_handle_realtime_alert_cooldown_from_db(tmp_path):
    """Yeni AlertManager instance, DB'deki realtime cooldown'i taniyor."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    alert = RealtimeAlert(
        alert_type="extended_silence",
        alert_level=1,
        message="3.5 saattir aktivite yok.",
        last_event_time="2025-03-01T09:00:00",
    )
    manager1, mock1 = _make_manager()
    manager1.handle_realtime_alert(alert, db_path=db_path)
    assert len(mock1.requests) == 1

    manager2, mock2 = _make_manager()
    manager2.handle_realtime_alert(alert, db_path=db_path)
    assert len(mock2.requests) == 0  # Cooldown icinde
