"""Pil izleme testleri."""

import json

from src.alerter.message_templates import render_battery_warning
from src.collector.event_processor import EventProcessor


def test_battery_warning_at_10_percent():
    """Pil %10 ise uyari donmeli."""
    proc = EventProcessor()
    payload = json.dumps({"occupancy": True, "battery": 10}).encode()

    result = proc.check_battery("sensor1", payload)

    assert result is not None
    assert result["sensor_id"] == "sensor1"
    assert result["battery"] == 10


def test_battery_ok_at_50_percent():
    """Pil %50 ise uyari donmemeli."""
    proc = EventProcessor()
    payload = json.dumps({"occupancy": True, "battery": 50}).encode()

    result = proc.check_battery("sensor1", payload)

    assert result is None


def test_battery_warning_not_repeated():
    """Ayni sensor icin tekrar uyari gonderilmemeli."""
    proc = EventProcessor()
    payload = json.dumps({"battery": 8}).encode()

    result1 = proc.check_battery("sensor1", payload)
    result2 = proc.check_battery("sensor1", payload)

    assert result1 is not None
    assert result2 is None


def test_battery_warning_reset_after_charge():
    """Pil > %20 oldugunda bayrak sifirlanmali, tekrar %10'da uyari gelmeli."""
    proc = EventProcessor()

    low = json.dumps({"battery": 8}).encode()
    result1 = proc.check_battery("sensor1", low)
    assert result1 is not None

    high = json.dumps({"battery": 80}).encode()
    proc.check_battery("sensor1", high)

    result3 = proc.check_battery("sensor1", low)
    assert result3 is not None


def test_battery_no_battery_field():
    """Payload'da battery alani yoksa None donmeli."""
    proc = EventProcessor()
    payload = json.dumps({"occupancy": True}).encode()

    result = proc.check_battery("sensor1", payload)

    assert result is None


def test_battery_invalid_payload():
    """Bozuk payload -> None donmeli."""
    proc = EventProcessor()

    result = proc.check_battery("sensor1", b"not_json_at_all")

    assert result is None


def test_render_battery_warning_template():
    """Pil uyari sablonu dogru render edilmeli."""
    text = render_battery_warning("mutfak_motion", 8)

    assert "mutfak_motion" in text
    assert "%8" in text
    assert "Pil" in text
