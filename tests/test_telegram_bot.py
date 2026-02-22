"""TelegramNotifier testleri - httpx mock ile."""

import httpx
import pytest

from src.alerter.telegram_bot import TelegramNotifier


class MockTransport(httpx.BaseTransport):
    """Deterministik mock transport."""

    def __init__(self, status_code=200, json_body=None):
        self._status_code = status_code
        self._json_body = json_body or {"ok": True}
        self.requests: list[httpx.Request] = []

    def handle_request(self, request):
        self.requests.append(request)
        return httpx.Response(self._status_code, json=self._json_body)


@pytest.fixture
def mock_ok():
    return MockTransport(status_code=200)


@pytest.fixture
def mock_fail():
    return MockTransport(status_code=500, json_body={"ok": False})


def test_send_message_success(mock_ok):
    """Basarili mesaj gonderimi -> True."""
    client = httpx.Client(transport=mock_ok)
    notifier = TelegramNotifier("test_token", ["111"], client=client)

    result = notifier.send_message("111", "Merhaba")

    assert result is True
    assert len(mock_ok.requests) == 1
    assert "/sendMessage" in str(mock_ok.requests[0].url)


def test_send_message_failure(mock_fail):
    """API 500 hatasi -> False."""
    client = httpx.Client(transport=mock_fail)
    notifier = TelegramNotifier("test_token", ["111"], client=client)

    result = notifier.send_message("111", "Merhaba")

    assert result is False


def test_send_message_disabled():
    """Token bos -> enabled=False, hicbir HTTP cagrisi yapilmaz."""
    mock = MockTransport()
    client = httpx.Client(transport=mock)
    notifier = TelegramNotifier("", ["111"], client=client)

    assert notifier.enabled is False
    result = notifier.send_message("111", "Merhaba")

    assert result is False
    assert len(mock.requests) == 0  # hic HTTP cagrisi yok


def test_send_to_all(mock_ok):
    """Tum chat_ids'e gonderir, sonuclari dict olarak dondurur."""
    client = httpx.Client(transport=mock_ok)
    notifier = TelegramNotifier("test_token", ["111", "222"], client=client)

    results = notifier.send_to_all("Test mesaji")

    assert results == {"111": True, "222": True}
    assert len(mock_ok.requests) == 2


def test_send_photo_success(mock_ok):
    """Fotograf basarili gonderilir -> True."""
    client = httpx.Client(transport=mock_ok)
    notifier = TelegramNotifier("test_token", ["111"], client=client)

    result = notifier.send_photo("111", b"fake_png_data", caption="Grafik")

    assert result is True
    assert len(mock_ok.requests) == 1
    assert "/sendPhoto" in str(mock_ok.requests[0].url)


def test_close_calls_client_close():
    """close() methodu httpx.Client.close()'u cagirmali."""
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    notifier = TelegramNotifier("test_token", ["111"], client=mock_client)

    notifier.close()

    mock_client.close.assert_called_once()
