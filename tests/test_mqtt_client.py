"""MQTTCollector testleri - mock mesaj, gercek DB, broker'a baglanma yok."""

import json

from src.collector.mqtt_client import MQTTCollector
from src.config import AppConfig
from src.database import get_db


class FakeMQTTMessage:
    """paho MQTTMessage mock'u - sadece topic ve payload."""

    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


def _make_collector(db_path: str, sensors=None) -> MQTTCollector:
    """Test icin MQTTCollector olustur (broker'a baglanmaz)."""
    config = AppConfig(
        mqtt={"broker": "localhost", "port": 1883, "topic_prefix": "zigbee2mqtt"},
        sensors=sensors or [
            {"id": "mutfak_motion", "channel": "presence", "type": "motion", "trigger_value": "on"},
            {"id": "buzdolabi_kapi", "channel": "fridge", "type": "contact", "trigger_value": "open"},
            {"id": "banyo_kapi", "channel": "bathroom", "type": "contact", "trigger_value": "open"},
            {"id": "dis_kapi", "channel": "door", "type": "contact", "trigger_value": "open"},
        ],
        database={"path": db_path},
    )
    return MQTTCollector(config, db_path)


def test_sensor_map_built_correctly(initialized_db):
    """Config'deki sensorler topic -> sensor haritasina dogru eslenmeli."""
    collector = _make_collector(initialized_db)

    assert "zigbee2mqtt/mutfak_motion" in collector._sensor_map
    assert "zigbee2mqtt/buzdolabi_kapi" in collector._sensor_map
    assert collector._sensor_map["zigbee2mqtt/mutfak_motion"].channel == "presence"
    assert len(collector._sensor_map) == 4


def test_on_message_motion_event_saved(initialized_db):
    """Motion sensor mesaji -> sensor_events tablosuna yazilmali."""
    collector = _make_collector(initialized_db)
    msg = FakeMQTTMessage(
        topic="zigbee2mqtt/mutfak_motion",
        payload=json.dumps({"occupancy": True}).encode(),
    )

    collector._on_message(None, None, msg)

    with get_db(initialized_db) as conn:
        rows = conn.execute("SELECT * FROM sensor_events").fetchall()

    assert len(rows) == 1
    assert rows[0]["sensor_id"] == "mutfak_motion"
    assert rows[0]["channel"] == "presence"
    assert rows[0]["value"] == "on"


def test_on_message_contact_event_saved(initialized_db):
    """Contact sensor (kapi acildi) -> DB'ye yazilmali."""
    collector = _make_collector(initialized_db)
    msg = FakeMQTTMessage(
        topic="zigbee2mqtt/buzdolabi_kapi",
        payload=json.dumps({"contact": False}).encode(),  # false = acik
    )

    collector._on_message(None, None, msg)

    with get_db(initialized_db) as conn:
        rows = conn.execute("SELECT * FROM sensor_events").fetchall()

    assert len(rows) == 1
    assert rows[0]["sensor_id"] == "buzdolabi_kapi"
    assert rows[0]["channel"] == "fridge"
    assert rows[0]["value"] == "open"


def test_on_message_unknown_topic_ignored(initialized_db):
    """Bilinmeyen topic -> DB'ye yazilmamali."""
    collector = _make_collector(initialized_db)
    msg = FakeMQTTMessage(
        topic="zigbee2mqtt/bilinmeyen_sensor",
        payload=json.dumps({"occupancy": True}).encode(),
    )

    collector._on_message(None, None, msg)

    with get_db(initialized_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sensor_events").fetchone()[0]

    assert count == 0


def test_on_message_bad_payload_ignored(initialized_db):
    """Bozuk payload -> DB'ye yazilmamali, hata vermemeli."""
    collector = _make_collector(initialized_db)
    msg = FakeMQTTMessage(
        topic="zigbee2mqtt/mutfak_motion",
        payload=b"garbled_data_xyz",
    )

    collector._on_message(None, None, msg)

    with get_db(initialized_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sensor_events").fetchone()[0]

    assert count == 0


def test_on_message_passive_event_not_saved(initialized_db):
    """Pasif event (occupancy=false) -> kaydedilmemeli."""
    collector = _make_collector(initialized_db)
    msg = FakeMQTTMessage(
        topic="zigbee2mqtt/mutfak_motion",
        payload=json.dumps({"occupancy": False}).encode(),
    )

    collector._on_message(None, None, msg)

    with get_db(initialized_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sensor_events").fetchone()[0]

    assert count == 0


def test_on_message_debounce(initialized_db):
    """Ayni sensordan 2 mesaj <30sn -> sadece 1 satir."""
    collector = _make_collector(initialized_db)

    msg1 = FakeMQTTMessage(
        topic="zigbee2mqtt/mutfak_motion",
        payload=json.dumps({"occupancy": True}).encode(),
    )
    msg2 = FakeMQTTMessage(
        topic="zigbee2mqtt/mutfak_motion",
        payload=json.dumps({"occupancy": True}).encode(),
    )

    # Iki mesaj hemen ard arda (<<30sn)
    collector._on_message(None, None, msg1)
    collector._on_message(None, None, msg2)

    with get_db(initialized_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sensor_events").fetchone()[0]

    assert count == 1  # debounce ile 2. mesaj filtrelendi
