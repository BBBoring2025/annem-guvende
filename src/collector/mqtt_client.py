"""MQTT baglantisi ve event dinleme - paho-mqtt 2.x.

Zigbee2MQTT'den sensor eventlerini toplar ve sensor_events tablosuna yazar.
paho-mqtt loop_start() ile background thread'de calisir, uvicorn event loop'unu bloklamaz.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from paho.mqtt.client import CallbackAPIVersion, Client, MQTTMessage

from src.collector.event_processor import EventProcessor
from src.config import AppConfig, SensorConfig
from src.database import get_db, get_system_state, set_system_state

logger = logging.getLogger("annem_guvende.collector")


class MQTTCollector:
    """Zigbee2MQTT'den sensor eventlerini toplar ve DB'ye yazar."""

    def __init__(self, config: AppConfig, db_path: str, battery_callback: Callable | None = None):
        self._config = config
        self._db_path = db_path
        self._processor = EventProcessor(debounce_seconds=30)
        self._battery_callback = battery_callback

        # Sensor haritasi: {topic: sensor_config_dict}
        self._sensor_map: dict[str, SensorConfig] = {}
        self._build_sensor_map()

        # paho-mqtt 2.x client
        self._client = Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id="annem_guvende",
        )
        self._broker = config.mqtt.broker
        self._port = config.mqtt.port
        self._topic_prefix = config.mqtt.topic_prefix

        # Callback'leri bagla
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        # LWT (Last Will and Testament) - beklenmeyen kopus durumunda
        self._client.will_set(
            topic=f"{self._topic_prefix}/annem_guvende/status",
            payload="offline",
            qos=1,
            retain=True,
        )

    def set_battery_callback(self, callback: Callable | None) -> None:
        """Pil uyari callback'ini ayarla (DI pattern)."""
        self._battery_callback = callback

    def _build_sensor_map(self) -> None:
        """Config'deki sensor listesinden topic -> sensor eslesmesi olustur."""
        prefix = self._config.mqtt.topic_prefix
        for sensor in self._config.sensors:
            topic = f"{prefix}/{sensor.id}"
            self._sensor_map[topic] = sensor
        logger.info("Sensor haritasi olusturuldu: %d sensor", len(self._sensor_map))

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties):
        """Baglanti kuruldu - sensor topic'lerine subscribe ol."""
        if reason_code == 0:
            logger.info("MQTT broker'a baglandi: %s:%d", self._broker, self._port)
            for topic in self._sensor_map:
                client.subscribe(topic)
                logger.info("Subscribe: %s", topic)
            # Online durumunu bildir
            client.publish(
                f"{self._topic_prefix}/annem_guvende/status",
                "online", qos=1, retain=True,
            )
        else:
            logger.error("MQTT baglanti hatasi: reason_code=%s", reason_code)

    def _on_message(self, client, userdata, message: MQTTMessage):
        """Yeni MQTT mesaji geldi - parse et, debounce, DB'ye yaz."""
        topic = message.topic
        sensor = self._sensor_map.get(topic)
        if sensor is None:
            logger.debug("Bilinmeyen topic: %s", topic)
            return

        # EventProcessor ile isle
        event = self._processor.process(
            sensor_id=sensor.id,
            channel=sensor.channel,
            sensor_type=sensor.type,
            trigger_value=sensor.trigger_value,
            raw_payload=message.payload,
        )

        if event is not None:
            self._save_event(event)
            self._update_fall_state(event)

        # Pil kontrolu
        if self._battery_callback is not None:
            warning = self._processor.check_battery(sensor.id, message.payload)
            if warning is not None:
                self._battery_callback(warning)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Baglanti koptu - paho 2.x otomatik reconnect yapar."""
        if reason_code == 0:
            logger.info("MQTT baglantisi kapandi (normal)")
        else:
            logger.warning("MQTT baglantisi koptu: reason_code=%s (otomatik reconnect aktif)", reason_code)

    def _update_fall_state(self, event: dict) -> None:
        """Banyo kullanim durumunu takip et (dusme tespiti icin).

        Banyo event'i geldiginde zamani kaydeder.
        Baska kanal event'i geldiginde (presence/kitchen/sleep/fridge)
        banyo zamani sifirlanir — kisi banyodan cikmis kabul edilir.
        """
        if event["channel"] == "bathroom":
            set_system_state(
                self._db_path, "last_bathroom_time", event["timestamp"]
            )
        else:
            last_bt = get_system_state(self._db_path, "last_bathroom_time", "")
            if last_bt:
                set_system_state(self._db_path, "last_bathroom_time", "")

    def _save_event(self, event: dict) -> None:
        """Normalize edilmis event'i sensor_events tablosuna kaydet."""
        with get_db(self._db_path) as conn:
            conn.execute(
                "INSERT INTO sensor_events (timestamp, sensor_id, channel, event_type, value) "
                "VALUES (?, ?, ?, ?, ?)",
                (event["timestamp"], event["sensor_id"], event["channel"],
                 event["event_type"], event["value"]),
            )
            conn.commit()
        logger.debug("Event kaydedildi: %s/%s", event["sensor_id"], event["value"])

    def start(self) -> None:
        """MQTT client'i baslat (background thread)."""
        self._client.connect(self._broker, self._port, keepalive=60)
        self._client.loop_start()
        logger.info("MQTT client baslatildi: %s:%d", self._broker, self._port)

    def stop(self) -> None:
        """MQTT client'i durdur."""
        # Offline durumunu bildir
        try:
            self._client.publish(
                f"{self._topic_prefix}/annem_guvende/status",
                "offline", qos=1, retain=True,
            )
        except Exception:
            pass
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTT client durduruldu")

    def is_connected(self) -> bool:
        """MQTT baglantisi aktif mi?"""
        return self._client.is_connected()
