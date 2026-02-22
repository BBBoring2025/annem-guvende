"""main.py lifespan testleri - MQTT startup hatasi korumasi."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.config import AppConfig


def _make_config(tmp_path):
    """Test icin AppConfig olustur."""
    return AppConfig(
        mqtt={"broker": "localhost", "port": 1883},
        sensors=[{"id": "s1", "channel": "presence", "type": "motion", "trigger_value": "on"}],
        telegram={"bot_token": "", "chat_ids": []},
        database={"path": str(tmp_path / "test.db")},
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
        heartbeat={"url": "", "device_id": "test"},
    )


def test_mqtt_failure_does_not_crash_startup(tmp_path):
    """MQTT broker yokken uygulama ayakta kalmali (dashboard + scheduler calisir)."""
    config_data = _make_config(tmp_path)

    with patch("src.main.load_config", return_value=config_data), \
         patch("src.main.MQTTCollector") as mock_mqtt:
        # start() exception firlat
        mock_collector = MagicMock()
        mock_collector.start.side_effect = ConnectionRefusedError("Connection refused")
        mock_collector.is_connected.return_value = False
        mock_mqtt.return_value = mock_collector

        from src.main import app

        # Uygulama baslamali ve health endpoint calismali
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("ok", "degraded")


def test_health_error_returns_503(tmp_path):
    """collect_system_metrics exception firlatirsa /health 503 donmeli."""
    config_data = _make_config(tmp_path)

    with patch("src.main.load_config", return_value=config_data), \
         patch("src.main.MQTTCollector") as mock_mqtt, \
         patch("src.main.collect_system_metrics", side_effect=RuntimeError("disk read error")):
        mock_collector = MagicMock()
        mock_collector.start.side_effect = ConnectionRefusedError("Connection refused")
        mock_collector.is_connected.return_value = False
        mock_mqtt.return_value = mock_collector

        from src.main import app

        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "error"
            assert "disk read error" in data["reason"]
