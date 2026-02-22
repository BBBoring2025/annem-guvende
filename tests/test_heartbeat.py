"""Heartbeat client testleri."""

import json

import httpx

from src.heartbeat.heartbeat_client import HeartbeatClient
from src.heartbeat.system_monitor import SystemMetrics


def _sample_metrics(**overrides) -> SystemMetrics:
    """Test icin ornek SystemMetrics."""
    defaults = dict(
        cpu_percent=25.0,
        memory_percent=60.0,
        disk_percent=45.0,
        cpu_temp=55.0,
        db_size_mb=10.0,
        last_event_age_minutes=5.0,
        today_event_count=100,
        uptime_seconds=86400.0,
    )
    defaults.update(overrides)
    return SystemMetrics(**defaults)


class MockTransport(httpx.BaseTransport):
    """Deterministik mock transport."""

    def __init__(self, status_code: int = 200):
        self.requests: list[httpx.Request] = []
        self._status_code = status_code

    def handle_request(self, request):
        self.requests.append(request)
        return httpx.Response(self._status_code, json={"ok": True})


class TimeoutTransport(httpx.BaseTransport):
    """Timeout simulate eden transport."""

    def handle_request(self, request):
        raise httpx.ConnectTimeout("Connection timed out")


# --- Enable/Disable testleri ---

def test_heartbeat_disabled_no_url():
    """URL bos -> enabled=False, send=False."""
    client = HeartbeatClient(url="")
    assert client.enabled is False

    metrics = _sample_metrics()
    assert client.send(metrics, mqtt_connected=True) is False


def test_heartbeat_enabled():
    """URL var -> enabled=True."""
    mock = MockTransport()
    client = HeartbeatClient(
        url="https://example.com/heartbeat",
        client=httpx.Client(transport=mock),
    )
    assert client.enabled is True


# --- Payload testleri ---

def test_build_payload_structure():
    """Payload dogru yapiyi icerir."""
    mock = MockTransport()
    client = HeartbeatClient(
        url="https://example.com/heartbeat",
        device_id="test-pi",
        client=httpx.Client(transport=mock),
    )

    metrics = _sample_metrics()
    payload = client.build_payload(metrics, mqtt_connected=True)

    assert payload["device_id"] == "test-pi"
    assert "timestamp" in payload
    assert payload["uptime_seconds"] == 86400.0

    # system nested dict
    assert payload["system"]["cpu_percent"] == 25.0
    assert payload["system"]["memory_percent"] == 60.0
    assert payload["system"]["disk_percent"] == 45.0
    assert payload["system"]["cpu_temp"] == 55.0

    # services nested dict
    assert payload["services"]["mqtt_connected"] is True
    assert payload["services"]["db_size_mb"] == 10.0
    assert payload["services"]["today_event_count"] == 100


def test_build_payload_null_temp():
    """cpu_temp=None -> payload'da None."""
    mock = MockTransport()
    client = HeartbeatClient(
        url="https://example.com/heartbeat",
        client=httpx.Client(transport=mock),
    )

    metrics = _sample_metrics(cpu_temp=None)
    payload = client.build_payload(metrics, mqtt_connected=True)

    assert payload["system"]["cpu_temp"] is None


# --- Send testleri ---

def test_send_success():
    """200 response -> True dondurur."""
    mock = MockTransport(status_code=200)
    client = HeartbeatClient(
        url="https://example.com/heartbeat",
        client=httpx.Client(transport=mock),
    )

    metrics = _sample_metrics()
    result = client.send(metrics, mqtt_connected=True)

    assert result is True
    assert len(mock.requests) == 1


def test_send_failure_500():
    """500 response -> False dondurur."""
    mock = MockTransport(status_code=500)
    client = HeartbeatClient(
        url="https://example.com/heartbeat",
        client=httpx.Client(transport=mock),
    )

    metrics = _sample_metrics()
    result = client.send(metrics, mqtt_connected=False)

    assert result is False


def test_send_timeout():
    """Timeout -> False, exception yok."""
    client = HeartbeatClient(
        url="https://example.com/heartbeat",
        client=httpx.Client(transport=TimeoutTransport()),
    )

    metrics = _sample_metrics()
    result = client.send(metrics, mqtt_connected=True)

    assert result is False  # exception yutulur


def test_send_payload_content():
    """Gonderilen JSON dogru icerige sahip."""
    mock = MockTransport()
    client = HeartbeatClient(
        url="https://example.com/heartbeat",
        device_id="test-pi",
        client=httpx.Client(transport=mock),
    )

    metrics = _sample_metrics(cpu_percent=42.5)
    client.send(metrics, mqtt_connected=True)

    # Request body'yi parse et
    request = mock.requests[0]
    body = json.loads(request.content)

    assert body["device_id"] == "test-pi"
    assert body["system"]["cpu_percent"] == 42.5
    assert body["services"]["mqtt_connected"] is True
