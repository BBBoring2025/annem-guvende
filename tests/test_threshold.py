"""Esik degerleri dogrulama testleri."""

from src.config import AppConfig
from src.detector.threshold_engine import get_alert_level


def _default_config():
    return AppConfig(
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0},
    )


def test_level_0_at_zero():
    """composite_z=0.0 -> Level 0 (Normal)."""
    assert get_alert_level(0.0, _default_config()) == 0


def test_level_0_below_gentle():
    """composite_z=1.5 -> Level 0 (Normal)."""
    assert get_alert_level(1.5, _default_config()) == 0


def test_level_1_at_boundary():
    """composite_z=2.0 tam sinirda -> Level 1 (Nazik)."""
    assert get_alert_level(2.0, _default_config()) == 1


def test_level_1_mid_range():
    """composite_z=2.5 -> Level 1."""
    assert get_alert_level(2.5, _default_config()) == 1


def test_level_2_at_boundary():
    """composite_z=3.0 -> Level 2 (Ciddi)."""
    assert get_alert_level(3.0, _default_config()) == 2


def test_level_2_mid_range():
    """composite_z=3.5 -> Level 2."""
    assert get_alert_level(3.5, _default_config()) == 2


def test_level_3_at_boundary():
    """composite_z=4.0 -> Level 3 (Acil)."""
    assert get_alert_level(4.0, _default_config()) == 3


def test_level_3_very_high():
    """composite_z=10.0 -> Level 3."""
    assert get_alert_level(10.0, _default_config()) == 3


def test_custom_thresholds():
    """Ozel esik degerleriyle calisir."""
    config = AppConfig(
        alerts={"z_threshold_gentle": 1.5, "z_threshold_serious": 2.5, "z_threshold_emergency": 3.5},
    )
    assert get_alert_level(1.4, config) == 0
    assert get_alert_level(1.5, config) == 1
    assert get_alert_level(2.5, config) == 2
    assert get_alert_level(3.5, config) == 3
