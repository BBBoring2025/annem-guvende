"""Pytest fixture'lari - tum testler icin ortak yapilar."""

import pytest

from src.config import AppConfig
from src.database import init_db


@pytest.fixture
def db_path(tmp_path):
    """Her test icin gecici veritabani dosya yolu olustur."""
    return str(tmp_path / "test.db")


@pytest.fixture
def initialized_db(db_path):
    """Tablolari olusturulmus gecici veritabani.

    Her test icin temiz bir DB dondurur.
    """
    init_db(db_path)
    return db_path


@pytest.fixture
def sample_config(tmp_path):
    """Test icin minimal konfigürasyon."""
    return AppConfig(
        mqtt={"broker": "localhost", "port": 1883, "topic_prefix": "zigbee2mqtt"},
        sensors=[{"id": "mutfak_motion", "channel": "presence", "type": "motion", "trigger_value": "on"}],
        model={"slot_minutes": 15, "learning_days": 14, "prior_alpha": 1.0, "prior_beta": 1.0, "awake_start_hour": 6, "awake_end_hour": 23},
        database={"path": str(tmp_path / "test.db")},
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
        telegram={"bot_token": "", "chat_ids": []},
        heartbeat={"enabled": False},
    )


@pytest.fixture
def sample_sensors():
    """Test icin 4 sensor config listesi."""
    return [
        {"id": "mutfak_motion", "channel": "presence", "type": "motion", "trigger_value": "on"},
        {"id": "buzdolabi_kapi", "channel": "fridge", "type": "contact", "trigger_value": "open"},
        {"id": "banyo_kapi", "channel": "bathroom", "type": "contact", "trigger_value": "open"},
        {"id": "dis_kapi", "channel": "door", "type": "contact", "trigger_value": "open"},
    ]


@pytest.fixture
def all_channels():
    """Tum kanal isimleri."""
    return ["presence", "fridge", "bathroom", "door"]
