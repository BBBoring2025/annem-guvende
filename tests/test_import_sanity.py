"""Import sanity testleri — Python 3.10+ union syntax crash kontrolu."""


def test_mqtt_client_importable():
    """MQTTCollector import edilebilmeli (callable | None syntax)."""
    from src.collector.mqtt_client import MQTTCollector
    assert MQTTCollector is not None


def test_simulator_importable():
    """SensorSimulator import edilebilmeli (int | None, callable | None syntax)."""
    from src.simulator.sensor_simulator import SensorSimulator
    assert SensorSimulator is not None
