"""EventProcessor testleri - payload parse ve debounce kurallari."""

import json
from datetime import datetime, timedelta

from src.collector.event_processor import EventProcessor

# --- parse_payload testleri ---

def test_parse_motion_json_occupancy_true():
    """Motion sensor: {"occupancy": true} -> aktif."""
    proc = EventProcessor()
    result = proc.parse_payload("motion", "on", json.dumps({"occupancy": True}).encode())
    assert result == (True, "on")


def test_parse_motion_json_occupancy_false():
    """Motion sensor: {"occupancy": false} -> pasif."""
    proc = EventProcessor()
    result = proc.parse_payload("motion", "on", json.dumps({"occupancy": False}).encode())
    assert result == (False, "off")


def test_parse_motion_string_on():
    """Motion sensor: "on" string -> aktif."""
    proc = EventProcessor()
    result = proc.parse_payload("motion", "on", b"on")
    assert result == (True, "on")


def test_parse_motion_string_off():
    """Motion sensor: "off" string -> pasif."""
    proc = EventProcessor()
    result = proc.parse_payload("motion", "on", b"off")
    assert result == (False, "off")


def test_parse_contact_json_false_means_open():
    """Contact sensor: {"contact": false} -> kapi acik (Zigbee2MQTT semantigi)."""
    proc = EventProcessor()
    result = proc.parse_payload("contact", "open", json.dumps({"contact": False}).encode())
    assert result == (True, "open")


def test_parse_contact_json_true_means_closed():
    """Contact sensor: {"contact": true} -> kapi kapali."""
    proc = EventProcessor()
    result = proc.parse_payload("contact", "open", json.dumps({"contact": True}).encode())
    assert result == (False, "closed")


def test_parse_contact_string_open():
    """Contact sensor: "open" string -> aktif (trigger_value=open)."""
    proc = EventProcessor()
    result = proc.parse_payload("contact", "open", b"open")
    assert result == (True, "open")


def test_parse_contact_string_closed():
    """Contact sensor: "closed" string -> pasif (trigger_value=open)."""
    proc = EventProcessor()
    result = proc.parse_payload("contact", "open", b"closed")
    assert result == (False, "closed")


def test_parse_unknown_format_returns_none():
    """Taninmayan payload -> None donmeli."""
    proc = EventProcessor()
    result = proc.parse_payload("motion", "on", b"foobar123")
    assert result is None


def test_parse_empty_payload_returns_none():
    """Bos payload -> None donmeli."""
    proc = EventProcessor()
    result = proc.parse_payload("motion", "on", b"")
    assert result is None


# --- debounce testleri ---

def test_debounce_first_event_always_passes():
    """Ilk event her zaman kabul edilir."""
    proc = EventProcessor(debounce_seconds=30)
    ts = datetime(2025, 2, 11, 10, 0, 0)
    assert proc.is_debounced("sensor1", ts) is False


def test_debounce_blocks_within_30s():
    """30sn icindeki tekrar event filtrelenir."""
    proc = EventProcessor(debounce_seconds=30)
    ts1 = datetime(2025, 2, 11, 10, 0, 0)
    ts2 = ts1 + timedelta(seconds=10)

    proc._record_event("sensor1", ts1)
    assert proc.is_debounced("sensor1", ts2) is True


def test_debounce_allows_after_30s():
    """30sn sonraki event kabul edilir."""
    proc = EventProcessor(debounce_seconds=30)
    ts1 = datetime(2025, 2, 11, 10, 0, 0)
    ts2 = ts1 + timedelta(seconds=31)

    proc._record_event("sensor1", ts1)
    assert proc.is_debounced("sensor1", ts2) is False


def test_debounce_exactly_30s_boundary():
    """Tam 30. saniyede event kabul edilir (sinir testi)."""
    proc = EventProcessor(debounce_seconds=30)
    ts1 = datetime(2025, 2, 11, 10, 0, 0)
    ts2 = ts1 + timedelta(seconds=30)

    proc._record_event("sensor1", ts1)
    assert proc.is_debounced("sensor1", ts2) is False


def test_debounce_different_sensors_independent():
    """Farkli sensorler icin debounce bagimsiz calisir."""
    proc = EventProcessor(debounce_seconds=30)
    ts1 = datetime(2025, 2, 11, 10, 0, 0)
    ts2 = ts1 + timedelta(seconds=5)

    proc._record_event("sensor1", ts1)
    assert proc.is_debounced("sensor2", ts2) is False


# --- process (tam pipeline) testleri ---

def test_process_motion_active_event():
    """Tam pipeline: aktif motion event -> normalize edilmis dict."""
    proc = EventProcessor(debounce_seconds=30)
    ts = datetime(2025, 2, 11, 10, 30, 0)

    result = proc.process(
        sensor_id="mutfak_motion",
        channel="presence",
        sensor_type="motion",
        trigger_value="on",
        raw_payload=json.dumps({"occupancy": True}).encode(),
        timestamp=ts,
    )

    assert result is not None
    assert result["sensor_id"] == "mutfak_motion"
    assert result["channel"] == "presence"
    assert result["value"] == "on"
    assert result["event_type"] == "state_change"


def test_process_passive_event_filtered():
    """Pasif event (occupancy=false) -> None (sadece aktif eventler kaydedilir)."""
    proc = EventProcessor()
    result = proc.process(
        sensor_id="mutfak_motion",
        channel="presence",
        sensor_type="motion",
        trigger_value="on",
        raw_payload=json.dumps({"occupancy": False}).encode(),
        timestamp=datetime(2025, 2, 11, 10, 0, 0),
    )
    assert result is None


def test_process_debounce_in_pipeline():
    """Pipeline icinde debounce calisiyor mu?"""
    proc = EventProcessor(debounce_seconds=30)
    ts1 = datetime(2025, 2, 11, 10, 0, 0)
    ts2 = ts1 + timedelta(seconds=10)

    result1 = proc.process(
        "mutfak_motion", "presence", "motion", "on",
        json.dumps({"occupancy": True}).encode(), ts1,
    )
    result2 = proc.process(
        "mutfak_motion", "presence", "motion", "on",
        json.dumps({"occupancy": True}).encode(), ts2,
    )

    assert result1 is not None
    assert result2 is None  # debounce ile filtrelendi


def test_process_contact_open():
    """Contact sensor: kapi acildi -> aktif event."""
    proc = EventProcessor()
    result = proc.process(
        sensor_id="buzdolabi_kapi",
        channel="fridge",
        sensor_type="contact",
        trigger_value="open",
        raw_payload=json.dumps({"contact": False}).encode(),
        timestamp=datetime(2025, 2, 11, 12, 0, 0),
    )

    assert result is not None
    assert result["channel"] == "fridge"
    assert result["value"] == "open"


# --- Cache cleanup testleri (FIX 12) ---

def test_stale_debounce_entries_cleaned():
    """1 saatten eski debounce kayitlari temizlenmeli."""
    proc = EventProcessor(debounce_seconds=30)
    old_time = datetime(2025, 3, 1, 10, 0, 0)  # 2 saat once
    now = datetime(2025, 3, 1, 12, 0, 0)

    proc._record_event("stale_sensor", old_time)
    assert "stale_sensor" in proc._last_event

    cleaned = proc._cleanup_stale_entries(now)
    assert cleaned == 1
    assert "stale_sensor" not in proc._last_event


def test_recent_entries_preserved():
    """5dk onceki debounce kayitlari korunmali."""
    proc = EventProcessor(debounce_seconds=30)
    recent_time = datetime(2025, 3, 1, 11, 55, 0)  # 5dk once
    now = datetime(2025, 3, 1, 12, 0, 0)

    proc._record_event("recent_sensor", recent_time)
    cleaned = proc._cleanup_stale_entries(now)

    assert cleaned == 0
    assert "recent_sensor" in proc._last_event


def test_cleanup_triggered_every_100_calls():
    """process() her 100 cagri sonra cleanup tetiklemeli."""
    proc = EventProcessor(debounce_seconds=30)
    old_time = datetime(2025, 3, 1, 10, 0, 0)
    proc._record_event("stale", old_time)

    # 99 cagri yap (henuz cleanup olmasin)
    base_ts = datetime(2025, 3, 1, 12, 0, 0)
    for i in range(99):
        proc.process(
            f"sensor_{i}", "presence", "motion", "on",
            json.dumps({"occupancy": True}).encode(),
            timestamp=base_ts + timedelta(seconds=i),
        )
    assert "stale" in proc._last_event  # henuz temizlenmemis

    # 100. cagri: cleanup tetiklenir
    proc.process(
        "sensor_100", "presence", "motion", "on",
        json.dumps({"occupancy": True}).encode(),
        timestamp=base_ts + timedelta(minutes=5),
    )
    assert "stale" not in proc._last_event  # temizlendi
