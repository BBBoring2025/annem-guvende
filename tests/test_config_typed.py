"""FIX 8 Tests: Typed Config (AppConfig).

- config.yml.example yuklenebiliyor
- Dosya yoksa default AppConfig donuyor
- sensor.channel attribute ile erisilebilir
- Gecersiz deger ValidationError atiyor
- Default degerler dogru
"""

import os

import pytest
from pydantic import ValidationError

from src.config import AppConfig, load_config


def test_load_valid_config():
    """config.yml.example yukleyince AppConfig donmeli."""
    example_path = os.path.join(
        os.path.dirname(__file__), "..", "config.yml.example"
    )
    config = load_config(example_path)

    assert isinstance(config, AppConfig)
    assert config.mqtt.broker == "localhost"
    assert config.model.learning_days == 14
    assert len(config.sensors) == 4


def test_load_missing_config(tmp_path):
    """Dosya yoksa default AppConfig donmeli."""
    # Olmayan bir path ver; fallback da olmayacak sekilde ayarla
    os.environ["ANNEM_CONFIG_PATH"] = str(tmp_path / "nonexistent.yml")
    try:
        config = load_config(str(tmp_path / "nonexistent.yml"))
    finally:
        os.environ.pop("ANNEM_CONFIG_PATH", None)

    assert isinstance(config, AppConfig)
    # Default degerler
    assert config.mqtt.broker == "localhost"
    assert config.model.learning_days == 14


def test_sensor_channel_access():
    """config.sensors[0].channel attribute ile erisilebilir."""
    config = AppConfig(
        sensors=[
            {"id": "test_sensor", "channel": "presence", "type": "motion", "trigger_value": "on"},
        ]
    )
    assert config.sensors[0].channel == "presence"
    assert config.sensors[0].id == "test_sensor"


def test_invalid_config_raises():
    """port='abc' gibi gecersiz deger ValidationError firlatmali."""
    with pytest.raises(ValidationError):
        AppConfig(mqtt={"port": "abc"})


def test_default_values():
    """Bos config ile tum default degerler dogru."""
    config = AppConfig()

    assert config.mqtt.broker == "localhost"
    assert config.mqtt.port == 1883
    assert config.model.slot_minutes == 15
    assert config.model.awake_start_hour == 6
    assert config.model.awake_end_hour == 23
    assert config.model.learning_days == 14
    assert config.alerts.z_threshold_gentle == 2.0
    assert config.alerts.min_train_days == 7
    assert config.database.path == "./data/annem_guvende.db"
    assert config.database.retention_days == 90
    assert config.system.vacation_mode is False
    assert config.telegram.bot_token == ""
    assert config.heartbeat.enabled is False


def test_env_override_dashboard_password(monkeypatch):
    """ANNEM_DASHBOARD_PASSWORD env → config.dashboard.password override."""
    monkeypatch.setenv("ANNEM_DASHBOARD_PASSWORD", "super_secret_42")
    config = load_config()
    assert config.dashboard.password == "super_secret_42"


def test_production_missing_username_raises(tmp_path, monkeypatch):
    """ANNEM_ENV=production + username='' → ValueError."""
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    monkeypatch.setenv("ANNEM_ENV", "production")
    config_data = AppConfig(
        dashboard={"username": "", "password": "guclu_sifre_123"},
        database={"path": str(tmp_path / "test.db")},
    )
    with patch("src.main.load_config", return_value=config_data), \
         patch("src.main.MQTTCollector") as mock_mqtt:
        mock_collector = MagicMock()
        mock_mqtt.return_value = mock_collector
        from src.main import app

        with pytest.raises((ValueError, SystemExit)):
            with TestClient(app):
                pass


def test_production_default_password_raises(tmp_path, monkeypatch):
    """ANNEM_ENV=production + varsayilan sifre → ValueError."""
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    monkeypatch.setenv("ANNEM_ENV", "production")
    config_data = AppConfig(
        dashboard={"username": "admin", "password": "change_me_immediately"},
        database={"path": str(tmp_path / "test.db")},
    )
    with patch("src.main.load_config", return_value=config_data), \
         patch("src.main.MQTTCollector") as mock_mqtt:
        mock_collector = MagicMock()
        mock_mqtt.return_value = mock_collector
        from src.main import app

        with pytest.raises((ValueError, SystemExit)):
            with TestClient(app):
                pass


def test_env_override_dashboard_username(monkeypatch):
    """ANNEM_DASHBOARD_USERNAME env → config.dashboard.username override."""
    monkeypatch.setenv("ANNEM_DASHBOARD_USERNAME", "env_admin_42")
    config = load_config()
    assert config.dashboard.username == "env_admin_42"


def test_production_blank_password_raises(tmp_path, monkeypatch):
    """ANNEM_ENV=production + password='' → ValueError."""
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    monkeypatch.setenv("ANNEM_ENV", "production")
    config_data = AppConfig(
        dashboard={"username": "admin", "password": ""},
        database={"path": str(tmp_path / "test.db")},
    )
    with patch("src.main.load_config", return_value=config_data), \
         patch("src.main.MQTTCollector") as mock_mqtt:
        mock_collector = MagicMock()
        mock_mqtt.return_value = mock_collector
        from src.main import app

        with pytest.raises((ValueError, SystemExit)):
            with TestClient(app):
                pass
