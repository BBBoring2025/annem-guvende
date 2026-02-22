"""Sahte sensor event uretici - test ve pilot simulasyonu icin.

MQTT kullanmaz. Dogrudan sensor_events tablosuna batch INSERT yapar.
Deterministik: seed ile tekrarlanabilir sonuclar uretir.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from src.database import get_db

logger = logging.getLogger("annem_guvende.simulator")

# Yasli birey gunluk rutin sablonu
# (saat_baslangic, saat_bitis, channel, sensor_id, (min_event, max_event))
NORMAL_ROUTINE = [
    (7, 8, "bathroom", "banyo_kapi", (2, 4)),       # Sabah banyo
    (7, 9, "presence", "mutfak_motion", (4, 8)),     # Kahvalti
    (8, 9, "fridge", "buzdolabi_kapi", (2, 4)),      # Buzdolabi
    (9, 12, "presence", "mutfak_motion", (6, 12)),   # Sabah aktivite
    (12, 13, "presence", "mutfak_motion", (3, 6)),   # Ogle yemegi
    (12, 13, "fridge", "buzdolabi_kapi", (2, 3)),    # Ogle buzdolabi
    (12, 13, "bathroom", "banyo_kapi", (1, 2)),      # Ogle banyo
    (14, 16, "presence", "mutfak_motion", (2, 5)),   # Ogleden sonra
    (17, 18, "presence", "mutfak_motion", (3, 6)),   # Aksam yemegi
    (17, 18, "fridge", "buzdolabi_kapi", (2, 4)),    # Aksam buzdolabi
    (19, 21, "presence", "mutfak_motion", (4, 8)),   # Aksam aktivite
    (19, 20, "door", "dis_kapi", (0, 2)),            # Kapi (bazen)
    (21, 22, "bathroom", "banyo_kapi", (1, 3)),      # Yatmadan banyo
]

# Trigger degerleri (channel -> value)
TRIGGER_VALUES = {
    "presence": "on",
    "fridge": "open",
    "bathroom": "open",
    "door": "open",
}

VALID_ANOMALY_TYPES = {"low_activity", "no_fridge", "late_wake", "no_bathroom"}


class SensorSimulator:
    """Sahte sensor eventleri ureterek DB'ye yazar.

    MQTT kullanmaz - dogrudan sensor_events tablosuna INSERT yapar.
    Test ve pilot simulasyonu icin tasarlanmistir.

    Args:
        db_path: Veritabani yolu
        seed: Rastgelelik tohumu (tekrarlanabilirlik icin)
    """

    def __init__(self, db_path: str, seed: int | None = None):
        self._db_path = db_path
        self._rng = random.Random(seed)

    def generate_normal_day(self, date: str) -> int:
        """Bir normal gunu simule et ve eventleri DB'ye yaz.

        Args:
            date: Hedef tarih "YYYY-MM-DD" formatinda

        Returns:
            Yazilan toplam event sayisi
        """
        events = self._build_normal_events(date)
        self._insert_events_batch(events)
        logger.info("Normal gun simule edildi: %s (%d event)", date, len(events))
        return len(events)

    def generate_anomaly_day(self, date: str, anomaly_type: str) -> int:
        """Anomali gunu simule et.

        Args:
            date: Hedef tarih
            anomaly_type: "low_activity" | "no_fridge" | "late_wake" | "no_bathroom"

        Returns:
            Yazilan toplam event sayisi

        Raises:
            ValueError: Gecersiz anomaly_type
        """
        if anomaly_type not in VALID_ANOMALY_TYPES:
            raise ValueError(
                f"Gecersiz anomaly_type: {anomaly_type}. "
                f"Gecerli tipler: {VALID_ANOMALY_TYPES}"
            )

        if anomaly_type == "low_activity":
            events = self._build_low_activity_events(date)
        elif anomaly_type == "no_fridge":
            events = self._build_filtered_events(date, exclude_channel="fridge")
        elif anomaly_type == "no_bathroom":
            events = self._build_filtered_events(date, exclude_channel="bathroom")
        elif anomaly_type == "late_wake":
            events = self._build_late_wake_events(date)

        self._insert_events_batch(events)
        logger.info(
            "Anomali gunu simule edildi: %s tip=%s (%d event)",
            date, anomaly_type, len(events),
        )
        return len(events)

    def run_pilot_simulation(
        self, start_date: str = "2025-01-01", days: int = 21
    ) -> dict:
        """Tam pilot senaryosu: 14 normal + 3 normal + 1 anomali + 3 normal.

        Args:
            start_date: Baslangic tarihi (YYYY-MM-DD)
            days: Toplam gun sayisi (default 21)

        Returns:
            {"total_events": int, "anomaly_date": str, "anomaly_type": str,
             "dates": list[str]}
        """
        base = datetime.strptime(start_date, "%Y-%m-%d")
        total_events = 0
        dates = []
        anomaly_day_index = 17  # 0-indexed: gun 18
        anomaly_type = "low_activity"
        anomaly_date = None

        for i in range(days):
            date = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            dates.append(date)

            if i == anomaly_day_index:
                count = self.generate_anomaly_day(date, anomaly_type)
                anomaly_date = date
            else:
                count = self.generate_normal_day(date)

            total_events += count

        logger.info(
            "Pilot simulasyon tamamlandi: %d gun, %d event, anomali=%s",
            days, total_events, anomaly_date,
        )

        return {
            "total_events": total_events,
            "anomaly_date": anomaly_date,
            "anomaly_type": anomaly_type,
            "dates": dates,
        }

    def run_demo(
        self,
        start_date: str = "2025-01-01",
        days: int = 21,
        day_duration_seconds: float = 3.0,
        callback: Callable | None = None,
    ) -> dict:
        """Demo modu: pilot simulasyonunu gorsel ilerleme ile calistir.

        Args:
            start_date: Baslangic tarihi (YYYY-MM-DD)
            days: Toplam gun sayisi (default 21)
            day_duration_seconds: Gunler arasi bekleme (saniye). 0=aninda.
            callback: Her gun sonunda cagirilir:
                callback(day_num, date, event_count, is_anomaly)

        Returns:
            {"total_events": int, "anomaly_date": str | None,
             "anomaly_type": str, "dates": list[str]}
        """
        base = datetime.strptime(start_date, "%Y-%m-%d")
        total_events = 0
        dates = []
        anomaly_day_index = 17  # 0-indexed: gun 18
        anomaly_type = "low_activity"
        anomaly_date = None

        for i in range(days):
            date = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            dates.append(date)
            is_anomaly = i == anomaly_day_index

            if is_anomaly:
                count = self.generate_anomaly_day(date, anomaly_type)
                anomaly_date = date
            else:
                count = self.generate_normal_day(date)

            total_events += count

            if callback is not None:
                callback(i + 1, date, count, is_anomaly)

            if day_duration_seconds > 0 and i < days - 1:
                time.sleep(day_duration_seconds)

        logger.info(
            "Demo simulasyon tamamlandi: %d gun, %d event, anomali=%s",
            days,
            total_events,
            anomaly_date,
        )

        return {
            "total_events": total_events,
            "anomaly_date": anomaly_date,
            "anomaly_type": anomaly_type,
            "dates": dates,
        }

    # --- Dahili event uretim metodlari ---

    def _build_normal_events(self, date: str) -> list[tuple]:
        """Normal gun icin event listesi olustur.

        Returns:
            [(timestamp_iso, sensor_id, channel, value), ...]
        """
        events = []
        for start_h, end_h, channel, sensor_id, (min_cnt, max_cnt) in NORMAL_ROUTINE:
            count = self._rng.randint(min_cnt, max_cnt)
            value = TRIGGER_VALUES[channel]
            for _ in range(count):
                ts = self._random_timestamp(date, start_h, end_h)
                events.append((ts, sensor_id, channel, value))
        return events

    def _build_low_activity_events(self, date: str) -> list[tuple]:
        """Cok az aktivite: sadece birkac presence eventi.

        Normal gunun ~%10'u kadar event.
        """
        events = []
        # Sadece 3-5 presence eventi, gunduz saatlerinde
        count = self._rng.randint(3, 5)
        for _ in range(count):
            ts = self._random_timestamp(date, 10, 16)
            events.append((ts, "mutfak_motion", "presence", "on"))
        return events

    def _build_filtered_events(
        self, date: str, exclude_channel: str
    ) -> list[tuple]:
        """Normal gun ama belirli kanal cikarilmis."""
        all_events = self._build_normal_events(date)
        return [e for e in all_events if e[2] != exclude_channel]

    def _build_late_wake_events(self, date: str) -> list[tuple]:
        """Gec uyanma: saat 11 oncesi hic event yok, sonrasi normal."""
        events = []
        for start_h, end_h, channel, sensor_id, (min_cnt, max_cnt) in NORMAL_ROUTINE:
            # Sadece 11:00 ve sonrasi
            effective_start = max(start_h, 11)
            if effective_start >= end_h:
                continue
            count = self._rng.randint(min_cnt, max_cnt)
            value = TRIGGER_VALUES[channel]
            for _ in range(count):
                ts = self._random_timestamp(date, effective_start, end_h)
                events.append((ts, sensor_id, channel, value))
        return events

    def _random_timestamp(self, date: str, start_hour: int, end_hour: int) -> str:
        """Belirtilen saat araligi icinde rastgele ISO timestamp uret.

        Args:
            date: YYYY-MM-DD
            start_hour: Baslangic saati (dahil)
            end_hour: Bitis saati (haric)

        Returns:
            ISO format timestamp (YYYY-MM-DDTHH:MM:SS)
        """
        base = datetime.strptime(date, "%Y-%m-%d")
        start = base + timedelta(hours=start_hour)
        end = base + timedelta(hours=end_hour)
        delta_seconds = int((end - start).total_seconds())
        offset = self._rng.randint(0, max(0, delta_seconds - 1))
        ts = start + timedelta(seconds=offset)
        return ts.strftime("%Y-%m-%dT%H:%M:%S")

    def _insert_events_batch(self, events: list[tuple]) -> None:
        """Toplu event INSERT (performans icin tek transaction).

        Args:
            events: [(timestamp, sensor_id, channel, value), ...]
        """
        if not events:
            return

        with get_db(self._db_path) as conn:
            conn.executemany(
                "INSERT INTO sensor_events "
                "(timestamp, sensor_id, channel, event_type, value) "
                "VALUES (?, ?, ?, 'state_change', ?)",
                events,
            )
            conn.commit()
