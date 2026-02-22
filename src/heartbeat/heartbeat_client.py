"""Dis VPS'e periyodik heartbeat gonderici.

Sync httpx ile HTTP POST. TelegramNotifier ile ayni
DI pattern: url bos ise sessizce devre disi.
"""

import logging
from datetime import datetime, timezone

import httpx

from src.heartbeat.system_monitor import SystemMetrics

logger = logging.getLogger("annem_guvende.heartbeat")

HEARTBEAT_TIMEOUT = 10.0


class HeartbeatClient:
    """Dis VPS'e heartbeat gonderici.

    URL bos ise sessizce devre disi kalir (graceful degradation).

    Args:
        url: Heartbeat endpoint URL (bos ise devre disi)
        device_id: Cihaz kimlik bilgisi
        client: Opsiyonel httpx.Client (test icin DI)
    """

    def __init__(
        self,
        url: str,
        device_id: str = "annem-pi",
        client: httpx.Client | None = None,
    ):
        self._url = url
        self._device_id = device_id
        self._enabled = bool(url)
        self._client = client or httpx.Client(timeout=HEARTBEAT_TIMEOUT)

        if not self._enabled:
            logger.info("Heartbeat devre disi (URL ayarlanmamis)")

    @property
    def enabled(self) -> bool:
        """Heartbeat aktif mi?"""
        return self._enabled

    def build_payload(
        self,
        metrics: SystemMetrics,
        mqtt_connected: bool,
    ) -> dict:
        """Heartbeat payload'ini olustur.

        Saf metot: sadece verilen metriklerden dict olusturur.

        Args:
            metrics: Sistem metrikleri
            mqtt_connected: MQTT baglanti durumu

        Returns:
            JSON-serializable dict
        """
        return {
            "device_id": self._device_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": metrics.uptime_seconds,
            "system": {
                "cpu_percent": metrics.cpu_percent,
                "memory_percent": metrics.memory_percent,
                "disk_percent": metrics.disk_percent,
                "cpu_temp": metrics.cpu_temp,
            },
            "services": {
                "mqtt_connected": mqtt_connected,
                "db_size_mb": metrics.db_size_mb,
                "last_event_minutes_ago": metrics.last_event_age_minutes,
                "today_event_count": metrics.today_event_count,
            },
        }

    def send(
        self,
        metrics: SystemMetrics,
        mqtt_connected: bool,
    ) -> bool:
        """Heartbeat gonder.

        Args:
            metrics: Sistem metrikleri
            mqtt_connected: MQTT baglanti durumu

        Returns:
            True = basarili, False = hata veya devre disi
        """
        if not self._enabled:
            return False

        payload = self.build_payload(metrics, mqtt_connected)

        try:
            response = self._client.post(self._url, json=payload)
            if response.status_code == 200:
                logger.debug("Heartbeat gonderildi")
                return True
            else:
                logger.error(
                    "Heartbeat hatasi: status=%d", response.status_code
                )
                return False
        except httpx.HTTPError as exc:
            logger.error("Heartbeat baglanti hatasi: %s", exc)
            return False
