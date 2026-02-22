"""Pilot checklist testleri."""

import os

# pilot_checklist.py scripts/ altinda — import icin sys.path'e ekle
import sys

import pytest

from src.config import AppConfig
from src.database import get_db, init_db

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"),
)
from pilot_checklist import PilotChecklist


@pytest.fixture
def checklist_db(tmp_path):
    """Checklist testi icin gecici DB."""
    db_path = str(tmp_path / "checklist.db")
    init_db(db_path)
    return db_path


@pytest.fixture
def valid_config():
    """Gecerli 4 sensorlu config."""
    return AppConfig(
        sensors=[
            {"id": "mutfak_motion", "channel": "presence", "type": "motion", "trigger_value": "on"},
            {"id": "buzdolabi_kapi", "channel": "fridge", "type": "contact", "trigger_value": "open"},
            {"id": "banyo_kapi", "channel": "bathroom", "type": "contact", "trigger_value": "open"},
            {"id": "dis_kapi", "channel": "door", "type": "contact", "trigger_value": "open"},
        ],
        mqtt={"broker": "localhost", "port": 1883},
        telegram={"bot_token": "", "chat_ids": []},
        heartbeat={"url": ""},
        database={},
    )


# --- Config sensor kontrolleri ---

def test_check_config_sensors_valid(checklist_db, valid_config):
    """Gecerli sensor config -> OK."""
    cl = PilotChecklist(valid_config, checklist_db)
    result = cl.check_config_sensors()

    assert result.status == "OK"
    assert "4 sensör" in result.message


def test_check_config_sensors_missing(checklist_db):
    """Eksik sensor tanimi -> FAIL."""
    config = AppConfig(sensors=[])
    cl = PilotChecklist(config, checklist_db)
    result = cl.check_config_sensors()

    assert result.status == "FAIL"
    assert "bulunamadı" in result.message


def test_check_config_sensors_incomplete(checklist_db):
    """Eksik alan -> FAIL."""
    config = AppConfig(sensors=[{"id": "test", "channel": "presence"}])
    cl = PilotChecklist(config, checklist_db)
    result = cl.check_config_sensors()

    assert result.status == "FAIL"


# --- DB kontrolleri ---

def test_check_db_writable(checklist_db, valid_config):
    """Yazilabilir DB -> OK."""
    cl = PilotChecklist(valid_config, checklist_db)
    result = cl.check_db_writable()

    assert result.status == "OK"
    assert "Yazılabilir" in result.message


def test_check_db_not_writable(valid_config):
    """Yazilabilir olmayan DB -> FAIL."""
    cl = PilotChecklist(valid_config, "/nonexistent/path/db.sqlite")
    result = cl.check_db_writable()

    assert result.status == "FAIL"


# --- Sensor event kontrolleri ---

def test_check_sensor_events_present(checklist_db, valid_config):
    """Event varsa -> OK."""
    # Biraz event ekle
    with get_db(checklist_db) as conn:
        for sid in ["mutfak_motion", "buzdolabi_kapi", "banyo_kapi", "dis_kapi"]:
            conn.execute(
                "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type) "
                "VALUES ('2025-01-01T10:00:00', ?, 'presence', 'state_change')",
                (sid,),
            )
        conn.commit()

    cl = PilotChecklist(valid_config, checklist_db)
    result = cl.check_sensor_events()

    assert result.status == "OK"


def test_check_sensor_events_empty(checklist_db, valid_config):
    """Event yoksa -> WARNING."""
    cl = PilotChecklist(valid_config, checklist_db)
    result = cl.check_sensor_events()

    assert result.status == "WARNING"
    assert "Henüz hiç event" in result.message


# --- MQTT kontrolleri ---

def test_check_mqtt_connection_fail(checklist_db, valid_config):
    """MQTT baglanti hatasi -> FAIL."""
    # Gercek broker olmadigi icin connect basarisiz olacak
    # (ya da mock kullanalim)
    from src.config import MqttConfig
    config = valid_config.model_copy(update={"mqtt": MqttConfig(broker="nonexistent.host.invalid", port=1883)})
    cl = PilotChecklist(config, checklist_db)
    result = cl.check_mqtt_connection()

    assert result.status == "FAIL"


# --- Dashboard kontrolleri ---

def test_check_dashboard_accessible_fail(checklist_db, valid_config):
    """Dashboard erisilemez -> FAIL (localhost:8099 kapali)."""
    cl = PilotChecklist(valid_config, checklist_db)
    result = cl.check_dashboard()

    # Test ortaminda dashboard calismadigi icin FAIL donecek
    assert result.status == "FAIL"


# --- Demo mode kontrolleri ---

def test_check_demo_mode_available(checklist_db, valid_config):
    """run_demo mevcut -> OK."""
    cl = PilotChecklist(valid_config, checklist_db)
    result = cl.check_demo_mode_available()

    assert result.status == "OK"
    assert "run_demo" in result.message


# --- Telegram komut kontrolleri ---

def test_check_telegram_commands_no_token(checklist_db, valid_config):
    """Token bos -> WARNING."""
    cl = PilotChecklist(valid_config, checklist_db)
    result = cl.check_telegram_commands()

    assert result.status == "WARNING"
    assert "token" in result.message.lower()
