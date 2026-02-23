"""Eskalasyon (Ölü Adamın Anahtarı) testleri — Sprint 15."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.alerter.alert_manager import AlertManager
from src.alerter.telegram_bot import TelegramNotifier
from src.config import AppConfig
from src.database import get_db, init_db
from src.detector.realtime_checks import RealtimeAlert
from src.jobs import escalation_check_job


def _make_config(**overrides) -> AppConfig:
    """Test icin config olustur."""
    telegram_kw = {
        "bot_token": "test_token",
        "chat_ids": ["111"],
        "emergency_chat_ids": ["999"],
        "escalation_minutes": 10,
    }
    telegram_kw.update(overrides)
    return AppConfig(telegram=telegram_kw)


# --- test_pending_alert_created_on_level3 ---


def test_pending_alert_created_on_level3(tmp_path):
    """Level 3 alarm → pending_alerts tablosunda 1 kayit, status='pending'."""
    db_path = str(tmp_path / "esc.db")
    init_db(db_path)

    config = _make_config()
    mock_notifier = MagicMock(spec=TelegramNotifier)
    mgr = AlertManager(config, mock_notifier)

    # Level 3 alert
    alert = RealtimeAlert(
        alert_type="fall_suspicion",
        alert_level=3,
        message="Test dusme suphesi",
        last_event_time="2025-03-20T10:00:00",
    )
    mgr.handle_realtime_alert(alert, db_path=db_path)

    # pending_alerts tablosunu kontrol et
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM pending_alerts").fetchall()

    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["alert_level"] == 3

    # send_to_all_with_ack cagrilmis olmali
    mock_notifier.send_to_all_with_ack.assert_called_once()


# --- test_pending_alert_not_created_on_level1 ---


def test_pending_alert_not_created_on_level1(tmp_path):
    """Level 1 alarm → pending_alerts tablosu bos."""
    db_path = str(tmp_path / "esc.db")
    init_db(db_path)

    config = _make_config()
    mock_notifier = MagicMock(spec=TelegramNotifier)
    mgr = AlertManager(config, mock_notifier)

    # Level 1 extended silence alert
    alert = RealtimeAlert(
        alert_type="extended_silence",
        alert_level=1,
        message="Test uzun sessizlik",
        last_event_time="2025-03-20T10:00:00",
    )
    mgr.handle_realtime_alert(alert, db_path=db_path)

    # pending_alerts tablosu bos olmali
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM pending_alerts").fetchall()

    assert len(rows) == 0

    # send_to_all_with_ack degil, send_to_all kullanilmis olmali
    mock_notifier.send_to_all_with_ack.assert_not_called()


# --- test_ack_updates_status ---


def test_ack_updates_status(tmp_path):
    """pending_alert INSERT → ack callback → status='acknowledged'."""
    db_path = str(tmp_path / "esc.db")
    init_db(db_path)

    # Manuel pending alert ekle
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pending_alerts (alert_level, message, timestamp, status) "
            "VALUES (3, 'Test alarm', '2025-03-20T10:00:00', 'pending')"
        )
        conn.commit()

    # Callback query simule et
    mock_client = MagicMock()
    mock_client.post.return_value = MagicMock(status_code=200)
    notifier = TelegramNotifier("test_token", ["111"], client=mock_client)

    callback_query = {
        "id": "cb_123",
        "data": "ack_1",
        "from": {"id": 111},
        "message": {"chat": {"id": 111}},
    }
    notifier._handle_callback_query(callback_query, db_path)

    # Status kontrol et
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM pending_alerts WHERE id = 1"
        ).fetchone()

    assert row["status"] == "acknowledged"


# --- test_escalation_after_timeout ---


def test_escalation_after_timeout(tmp_path):
    """10+ dk onceki pending alert → escalation_check_job → status='escalated'."""
    db_path = str(tmp_path / "esc.db")
    init_db(db_path)

    config = _make_config(escalation_minutes=10)

    # 15 dakika onceki pending alert
    old_ts = (datetime.now() - timedelta(minutes=15)).isoformat()
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pending_alerts (alert_level, message, timestamp, status) "
            "VALUES (3, 'Eski alarm mesaji', ?, 'pending')",
            (old_ts,),
        )
        conn.commit()

    mock_notifier = MagicMock(spec=TelegramNotifier)
    escalation_check_job(db_path, config, mock_notifier)

    # Status escalated olmali
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM pending_alerts WHERE id = 1"
        ).fetchone()

    assert row["status"] == "escalated"

    # Emergency kisi(ler)e mesaj gonderilmis olmali
    mock_notifier.send_message.assert_called_once()
    call_args = mock_notifier.send_message.call_args
    assert call_args[0][0] == "999"  # emergency_chat_id
    assert "ESKALASYON" in call_args[0][1]


# --- test_escalation_skipped_if_acknowledged ---


def test_escalation_skipped_if_acknowledged(tmp_path):
    """acknowledged alert → escalation_check_job → hicbir sey yapma."""
    db_path = str(tmp_path / "esc.db")
    init_db(db_path)

    config = _make_config(escalation_minutes=10)

    # 15 dakika onceki ama acknowledged alert
    old_ts = (datetime.now() - timedelta(minutes=15)).isoformat()
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pending_alerts (alert_level, message, timestamp, status) "
            "VALUES (3, 'Onaylanan alarm', ?, 'acknowledged')",
            (old_ts,),
        )
        conn.commit()

    mock_notifier = MagicMock(spec=TelegramNotifier)
    escalation_check_job(db_path, config, mock_notifier)

    # Mesaj gonderilmemis olmali
    mock_notifier.send_message.assert_not_called()

    # Status hala acknowledged
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM pending_alerts WHERE id = 1"
        ).fetchone()

    assert row["status"] == "acknowledged"


# --- test_escalation_skipped_if_no_emergency_ids ---


def test_escalation_skipped_if_no_emergency_ids(tmp_path):
    """emergency_chat_ids=[] → escalation_check_job → hicbir sey yapma."""
    db_path = str(tmp_path / "esc.db")
    init_db(db_path)

    config = _make_config(emergency_chat_ids=[])

    # 15 dakika onceki pending alert
    old_ts = (datetime.now() - timedelta(minutes=15)).isoformat()
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pending_alerts (alert_level, message, timestamp, status) "
            "VALUES (3, 'Alarm', ?, 'pending')",
            (old_ts,),
        )
        conn.commit()

    mock_notifier = MagicMock(spec=TelegramNotifier)
    escalation_check_job(db_path, config, mock_notifier)

    # Mesaj gonderilmemis olmali
    mock_notifier.send_message.assert_not_called()

    # Status hala pending (eskalasyon yapilmadi)
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM pending_alerts WHERE id = 1"
        ).fetchone()

    assert row["status"] == "pending"


# --- test_send_message_with_ack_has_inline_keyboard ---


def test_send_message_with_ack_has_inline_keyboard():
    """send_message_with_ack → payload'da reply_markup var."""
    mock_client = MagicMock()
    mock_response = MagicMock(status_code=200)
    mock_client.post.return_value = mock_response

    notifier = TelegramNotifier("test_token", ["111"], client=mock_client)
    result = notifier.send_message_with_ack("111", "Test mesaj", alert_id=42)

    assert result is True

    # POST cagrisinin payload'ini kontrol et
    call_args = mock_client.post.call_args
    payload = call_args[1]["json"]

    assert "reply_markup" in payload
    assert "inline_keyboard" in payload["reply_markup"]
    keyboard = payload["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 1
    assert len(keyboard[0]) == 1
    assert keyboard[0][0]["callback_data"] == "ack_42"
    assert "Gördüm" in keyboard[0][0]["text"]


# --- test_ack_unauthorized_chat_ignored ---


def test_ack_unauthorized_chat_ignored(tmp_path):
    """Yetkisiz chat_id'den gelen callback_query → status degismez."""
    db_path = str(tmp_path / "esc.db")
    init_db(db_path)

    # Manuel pending alert ekle
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO pending_alerts (alert_level, message, timestamp, status) "
            "VALUES (3, 'Test alarm', '2025-03-20T10:00:00', 'pending')"
        )
        conn.commit()

    # Yetkisiz chat_id (999) ile callback query simule et
    mock_client = MagicMock()
    mock_client.post.return_value = MagicMock(status_code=200)
    notifier = TelegramNotifier("test_token", ["111"], client=mock_client)

    callback_query = {
        "id": "cb_456",
        "data": "ack_1",
        "from": {"id": 999},
        "message": {"chat": {"id": 999}},
    }
    notifier._handle_callback_query(callback_query, db_path)

    # Status hala pending olmali (degismemis)
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM pending_alerts WHERE id = 1"
        ).fetchone()

    assert row["status"] == "pending"

    # answerCallbackQuery cagrilmis olmali (buton loading kalmamali)
    post_calls = mock_client.post.call_args_list
    answer_calls = [c for c in post_calls if "answerCallbackQuery" in str(c)]
    assert len(answer_calls) >= 1
