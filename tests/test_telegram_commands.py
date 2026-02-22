"""Telegram komut isleyici testleri (FIX 16)."""

import json

import httpx

from src.alerter.telegram_bot import TelegramNotifier
from src.database import get_system_state, init_db, set_system_state

# --- Mock Transport ---


class CommandMockTransport(httpx.BaseTransport):
    """getUpdates ve sendMessage icin mock transport.

    updates: getUpdates'ten donecek update listesi.
    sent_messages: sendMessage cagrilarini yakalar.
    """

    def __init__(self, updates: list[dict] | None = None):
        self.updates = updates or []
        self.sent_messages: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        if "/getUpdates" in url:
            return httpx.Response(
                200,
                json={"ok": True, "result": self.updates},
            )

        if "/sendMessage" in url:
            body = json.loads(request.content)
            self.sent_messages.append(body)
            return httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": len(self.sent_messages)}},
            )

        return httpx.Response(404)


def _make_update(update_id: int, chat_id: int, text: str) -> dict:
    """Sahte Telegram update olustur."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": chat_id},
            "text": text,
        },
    }


def _make_notifier(updates: list[dict], chat_ids: list[str]) -> tuple:
    """Test notifier ve transport olustur."""
    transport = CommandMockTransport(updates=updates)
    client = httpx.Client(transport=transport)
    notifier = TelegramNotifier(
        bot_token="test_token_123",
        chat_ids=chat_ids,
        client=client,
    )
    return notifier, transport


def _make_config():
    """Minimal AppConfig olustur."""
    from src.config import load_config

    return load_config()


# --- Tests ---


def test_yardim_command(tmp_path):
    """/yardim komutu 'Komutlar' iceren mesaj gondermeli."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    config = _make_config()

    updates = [_make_update(100, 12345, "/yardim")]
    notifier, transport = _make_notifier(updates, ["12345"])

    notifier.process_commands(db_path, config)

    assert len(transport.sent_messages) == 1
    assert "Komutlar" in transport.sent_messages[0]["text"]


def test_tatil_command(tmp_path):
    """/tatil komutu vacation_mode=true yapmali."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    config = _make_config()

    updates = [_make_update(200, 12345, "/tatil")]
    notifier, transport = _make_notifier(updates, ["12345"])

    notifier.process_commands(db_path, config)

    assert len(transport.sent_messages) == 1
    assert "Tatil" in transport.sent_messages[0]["text"] or "tatil" in transport.sent_messages[0]["text"]
    val = get_system_state(db_path, "vacation_mode")
    assert val == "true"


def test_evdeyim_command(tmp_path):
    """/evdeyim komutu vacation_mode=false yapmali."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    config = _make_config()
    set_system_state(db_path, "vacation_mode", "true")

    updates = [_make_update(300, 12345, "/evdeyim")]
    notifier, transport = _make_notifier(updates, ["12345"])

    notifier.process_commands(db_path, config)

    assert len(transport.sent_messages) == 1
    val = get_system_state(db_path, "vacation_mode")
    assert val == "false"


def test_durum_command(tmp_path):
    """/durum komutu 'Sistem Durumu' iceren mesaj gondermeli."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    config = _make_config()

    updates = [_make_update(400, 12345, "/durum")]
    notifier, transport = _make_notifier(updates, ["12345"])

    notifier.process_commands(db_path, config)

    assert len(transport.sent_messages) == 1
    assert "Sistem Durumu" in transport.sent_messages[0]["text"]


def test_unknown_chat_id_ignored(tmp_path):
    """Kayitli olmayan chat_id mesajlari islenmemeli."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    config = _make_config()

    updates = [_make_update(500, 99999, "/yardim")]
    notifier, transport = _make_notifier(updates, ["12345"])

    notifier.process_commands(db_path, config)

    assert len(transport.sent_messages) == 0


def test_offset_persisted(tmp_path):
    """Islenen offset DB'ye kaydedilmeli."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    config = _make_config()

    updates = [_make_update(700, 12345, "/yardim")]
    notifier, transport = _make_notifier(updates, ["12345"])

    notifier.process_commands(db_path, config)

    saved = get_system_state(db_path, "telegram_last_offset", "0")
    assert int(saved) == 701


def test_start_command_sends_help(tmp_path):
    """/start komutu yardim mesaji gondermeli."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    config = _make_config()

    updates = [_make_update(800, 12345, "/start")]
    notifier, transport = _make_notifier(updates, ["12345"])

    notifier.process_commands(db_path, config)

    assert len(transport.sent_messages) == 1
    assert "Komutlar" in transport.sent_messages[0]["text"]
