"""Composite z-skoru → kademeli alarm seviyesi.

Level 0: Normal           (composite_z < gentle)
Level 1: Nazik kontrol    (gentle <= composite_z < serious)
Level 2: Ciddi            (serious <= composite_z < emergency)
Level 3: Acil             (composite_z >= emergency)
"""

from src.config import AppConfig


def get_alert_level(composite_z: float, config: AppConfig) -> int:
    """Composite z-skoru icin alarm seviyesi belirle.

    Args:
        composite_z: Anomali skoru (>= 0)
        config: Uygulama konfigurasyonu (alerts esikleri icermeli)

    Returns:
        0 = Normal, 1 = Nazik, 2 = Ciddi, 3 = Acil
    """
    t_gentle = config.alerts.z_threshold_gentle
    t_serious = config.alerts.z_threshold_serious
    t_emergency = config.alerts.z_threshold_emergency

    if composite_z >= t_emergency:
        return 3
    elif composite_z >= t_serious:
        return 2
    elif composite_z >= t_gentle:
        return 1
    return 0
