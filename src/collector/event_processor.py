"""Ham sensor mesajlarini normalize et ve debounce uygula."""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("annem_guvende.collector")


class EventProcessor:
    """Sensor mesajlarini normalize eder ve debounce uygular.

    Debounce kurali: Ayni sensor_id'den 30 saniye icinde
    gelen tekrar eventler filtrelenir (motion sensorleri cok sik tetiklenir).
    """

    def __init__(self, debounce_seconds: int = 30):
        self._debounce_seconds = debounce_seconds
        # {sensor_id: son kabul edilen event zamani}
        self._last_event: dict[str, datetime] = {}
        self._process_count: int = 0
        # Pil izleme
        self._battery_levels: dict[str, int] = {}
        self._battery_warning_sent: dict[str, bool] = {}

    def parse_payload(
        self, sensor_type: str, trigger_value: str, raw_payload: bytes
    ) -> tuple[bool, str] | None:
        """Ham MQTT payload'ini parse et.

        Returns:
            (is_active, value_str) - ornegin (True, "on") veya (False, "closed")
            None - taninmayan format, atlanacak
        """
        try:
            text = raw_payload.decode("utf-8").strip()
        except (UnicodeDecodeError, AttributeError):
            logger.warning("Payload decode edilemedi")
            return None

        if not text:
            return None

        # JSON payload dene
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return self._parse_json_payload(data, sensor_type, trigger_value)
        except (json.JSONDecodeError, ValueError):
            pass

        # Duz string payload dene
        return self._parse_string_payload(text, sensor_type, trigger_value)

    def _parse_json_payload(
        self, data: dict, sensor_type: str, trigger_value: str
    ) -> tuple[bool, str] | None:
        """JSON formatindaki payload'i parse et."""
        if sensor_type == "motion":
            if "occupancy" in data:
                is_active = bool(data["occupancy"])
                return (is_active, "on" if is_active else "off")
        elif sensor_type == "contact":
            if "contact" in data:
                # Zigbee2MQTT: contact=false -> kapi ACIK (sensor temassiz)
                contact_val = bool(data["contact"])
                is_open = not contact_val
                if trigger_value == "open":
                    return (is_open, "open" if is_open else "closed")
                else:
                    return (contact_val, "closed" if contact_val else "open")

        logger.warning("JSON payload taninmadi: type=%s, keys=%s", sensor_type, list(data.keys()))
        return None

    def _parse_string_payload(
        self, text: str, sensor_type: str, trigger_value: str
    ) -> tuple[bool, str] | None:
        """Duz string formatindaki payload'i parse et."""
        lower = text.lower()

        if sensor_type == "motion":
            if lower in ("on", "true"):
                return (True, "on")
            elif lower in ("off", "false"):
                return (False, "off")
        elif sensor_type == "contact":
            if lower == "open":
                return (trigger_value == "open", "open")
            elif lower == "closed":
                return (trigger_value != "open", "closed")

        logger.warning("String payload taninmadi: type=%s, text=%s", sensor_type, text)
        return None

    def is_debounced(self, sensor_id: str, timestamp: datetime) -> bool:
        """Bu event debounce kurali ile filtrelenmeli mi?

        True donerse event atlanacak (cok yakinda ayni sensor tetiklenmis).
        """
        last = self._last_event.get(sensor_id)
        if last is None:
            return False
        return (timestamp - last) < timedelta(seconds=self._debounce_seconds)

    def _record_event(self, sensor_id: str, timestamp: datetime) -> None:
        """Debounce tablosunu guncelle (son kabul edilen event zamani)."""
        self._last_event[sensor_id] = timestamp

    def _cleanup_stale_entries(self, now: datetime | None = None) -> int:
        """1 saatten eski debounce kayitlarini temizle.

        Returns:
            Silinen kayit sayisi
        """
        if now is None:
            now = datetime.now()
        cutoff = now - timedelta(hours=1)
        stale = [k for k, v in self._last_event.items() if v < cutoff]
        for k in stale:
            del self._last_event[k]
        return len(stale)

    def process(
        self,
        sensor_id: str,
        channel: str,
        sensor_type: str,
        trigger_value: str,
        raw_payload: bytes,
        timestamp: datetime | None = None,
    ) -> dict | None:
        """Tam pipeline: parse -> debounce -> normalize.

        Returns:
            Normalize edilmis event dict veya None (filtrelendi/taninmadi).
        """
        if timestamp is None:
            timestamp = datetime.now()

        # Periyodik cleanup (her 100 cagri)
        self._process_count += 1
        if self._process_count % 100 == 0:
            self._cleanup_stale_entries(timestamp)

        # 1. Payload parse et
        result = self.parse_payload(sensor_type, trigger_value, raw_payload)
        if result is None:
            return None

        is_active, value_str = result

        # Sadece aktif eventleri kaydet (trigger anini yakala)
        if not is_active:
            return None

        # 2. Debounce kontrolu
        if self.is_debounced(sensor_id, timestamp):
            logger.debug("Debounce: %s (30sn icinde tekrar)", sensor_id)
            return None

        # 3. Kabul et ve kaydet
        self._record_event(sensor_id, timestamp)

        return {
            "sensor_id": sensor_id,
            "channel": channel,
            "timestamp": timestamp.isoformat(),
            "event_type": "state_change",
            "value": value_str,
        }

    def check_battery(self, sensor_id: str, raw_payload: bytes) -> dict | None:
        """Pil seviyesini kontrol et, dusuk ise uyari dict'i dondur.

        Args:
            sensor_id: Sensor ID
            raw_payload: Ham MQTT payload (JSON icinde "battery" alani aranir)

        Returns:
            {"sensor_id": str, "battery": int} veya None
        """
        try:
            text = raw_payload.decode("utf-8").strip()
            data = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        battery = data.get("battery")
        if battery is None:
            return None

        try:
            battery = int(battery)
        except (TypeError, ValueError):
            return None

        self._battery_levels[sensor_id] = battery

        # Pil > %20: uyari bayragi sifirla (pil degistirilmis)
        if battery > 20:
            self._battery_warning_sent[sensor_id] = False
            return None

        # Pil <= %10 ve daha once uyari gonderilmediyse
        if battery <= 10 and not self._battery_warning_sent.get(sensor_id, False):
            self._battery_warning_sent[sensor_id] = True
            logger.warning("Dusuk pil: %s = %%%d", sensor_id, battery)
            return {"sensor_id": sensor_id, "battery": battery}

        return None
