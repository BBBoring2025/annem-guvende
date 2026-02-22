#!/usr/bin/env python3
"""Pilot oncesi sistem hazirlik kontrolu.

Kullanim:
    python scripts/pilot_checklist.py
    python scripts/pilot_checklist.py --config /path/to/config.yml
"""

import argparse
import os
import sys
from dataclasses import dataclass

# Proje kokunu path'e ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import AppConfig, load_config
from src.database import get_db

REQUIRED_CHANNELS = {"presence", "fridge", "bathroom", "door"}


@dataclass
class CheckResult:
    """Tek bir kontrol sonucu."""

    name: str
    status: str  # "OK", "FAIL", "WARNING"
    message: str


class PilotChecklist:
    """Pilot oncesi sistem hazirlik kontrolu.

    Args:
        config: Uygulama konfigurasyonu
        db_path: Veritabani yolu
    """

    def __init__(self, config: AppConfig, db_path: str):
        self._config = config
        self._db_path = db_path
        self._results: list[CheckResult] = []

    def check_config_sensors(self) -> CheckResult:
        """Config'deki sensor tanimlari gecerli mi?"""
        sensors = self._config.sensors
        if not sensors:
            return CheckResult(
                "Config sensörleri", "FAIL",
                "Sensör tanımı bulunamadı",
            )

        errors = []
        channels_found = set()
        for s in sensors:
            for field in ("id", "channel", "type", "trigger_value"):
                if not getattr(s, field, ""):
                    errors.append(f"{s.id}: '{field}' alanı eksik")
            if s.channel:
                channels_found.add(s.channel)

        if errors:
            return CheckResult(
                "Config sensörleri", "FAIL",
                "; ".join(errors),
            )

        missing = REQUIRED_CHANNELS - channels_found
        if missing:
            return CheckResult(
                "Config sensörleri", "WARNING",
                f"Eksik kanallar: {', '.join(missing)}",
            )

        return CheckResult(
            "Config sensörleri", "OK",
            f"{len(sensors)} sensör tanımlı",
        )

    def check_mqtt_connection(self) -> CheckResult:
        """MQTT broker'a baglanabiliyor mu?"""
        broker = self._config.mqtt.broker
        port = self._config.mqtt.port

        try:
            import paho.mqtt.client as mqtt_client
            client = mqtt_client.Client(
                mqtt_client.CallbackAPIVersion.VERSION2,
                client_id="pilot_check",
            )
            client.connect(broker, port, keepalive=5)
            client.disconnect()
            return CheckResult(
                "MQTT bağlantısı", "OK",
                f"{broker}:{port} bağlandı",
            )
        except Exception as exc:
            return CheckResult(
                "MQTT bağlantısı", "FAIL",
                f"{broker}:{port} - {exc}",
            )

    def check_sensor_events(self) -> CheckResult:
        """Her sensorden en az 1 event geldi mi?"""
        try:
            sensors = self._config.sensors
            sensor_ids = {s.id for s in sensors if s.id}

            with get_db(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT sensor_id FROM sensor_events"
                ).fetchall()

            found = {r["sensor_id"] for r in rows}
            missing = sensor_ids - found

            if not found:
                return CheckResult(
                    "Sensör eventleri", "WARNING",
                    "Henüz hiç event kaydedilmemiş",
                )

            if missing:
                return CheckResult(
                    "Sensör eventleri", "WARNING",
                    f"Event yok: {', '.join(missing)}",
                )

            return CheckResult(
                "Sensör eventleri", "OK",
                f"{len(found)} sensörden event gelmiş",
            )
        except Exception as exc:
            return CheckResult(
                "Sensör eventleri", "FAIL",
                str(exc),
            )

    def check_telegram(self) -> CheckResult:
        """Telegram bot token gecerli mi?"""
        bot_token = self._config.telegram.bot_token
        if not bot_token:
            return CheckResult(
                "Telegram", "WARNING",
                "Bot token ayarlanmamış (bildirimler devre dışı)",
            )

        try:
            import httpx
            resp = httpx.get(
                f"https://api.telegram.org/bot{bot_token}/getMe",
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                username = data.get("result", {}).get("username", "?")
                return CheckResult(
                    "Telegram", "OK",
                    f"Bot aktif: @{username}",
                )
            else:
                return CheckResult(
                    "Telegram", "FAIL",
                    f"API hatası: {resp.status_code}",
                )
        except Exception as exc:
            return CheckResult(
                "Telegram", "FAIL",
                str(exc),
            )

    def check_heartbeat(self) -> CheckResult:
        """Heartbeat VPS'e ulasabiliyor mu?"""
        url = self._config.heartbeat.url

        if not url:
            return CheckResult(
                "Heartbeat", "WARNING",
                "URL ayarlanmamış (devre dışı)",
            )

        try:
            import httpx
            resp = httpx.get(url, timeout=5.0)
            return CheckResult(
                "Heartbeat", "OK",
                f"{url} erişilebilir (HTTP {resp.status_code})",
            )
        except Exception as exc:
            return CheckResult(
                "Heartbeat", "FAIL",
                f"{url} - {exc}",
            )

    def check_db_writable(self) -> CheckResult:
        """DB'ye yazilabiliyor mu?"""
        try:
            with get_db(self._db_path) as conn:
                # Test insert + delete
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (99999)"
                )
                conn.execute(
                    "DELETE FROM schema_version WHERE version = 99999"
                )
                conn.commit()

            # Boyut bilgisi
            size_mb = os.path.getsize(self._db_path) / (1024 * 1024)
            return CheckResult(
                "Veritabanı", "OK",
                f"Yazılabilir ({size_mb:.1f} MB)",
            )
        except Exception as exc:
            return CheckResult(
                "Veritabanı", "FAIL",
                str(exc),
            )

    def check_pet_situation(self) -> CheckResult:
        """Evcil hayvan durumu kontrol hatirlatmasi."""
        return CheckResult(
            "Evcil Hayvan Kontrolü", "WARNING",
            "Evde kedi, köpek veya başka evcil hayvan var mı? "
            "Varsa: Pet-immune PIR sensör kullanılmalı VEYA sensörler yerden "
            "min. 1.2m yüksekliğe, aşağı bakmayacak şekilde monte edilmeli. "
            "Hayvan hareketleri presence kanalını bozabilir, kurulum buna göre ayarlanmalı.",
        )

    def check_dashboard(self) -> CheckResult:
        """Dashboard (port 8099) erisilebilir mi?"""
        try:
            import httpx
            resp = httpx.get("http://localhost:8099/health", timeout=5.0)
            if resp.status_code == 200:
                return CheckResult(
                    "Dashboard", "OK",
                    "http://localhost:8099 erişilebilir",
                )
            else:
                return CheckResult(
                    "Dashboard", "FAIL",
                    f"HTTP {resp.status_code}",
                )
        except Exception as exc:
            return CheckResult(
                "Dashboard", "FAIL",
                str(exc),
            )

    def check_demo_mode_available(self) -> CheckResult:
        """Demo modu calisabiliyor mu? (run_demo metodu var mi?)"""
        try:
            from src.simulator.sensor_simulator import SensorSimulator
            if hasattr(SensorSimulator, "run_demo"):
                return CheckResult(
                    "Demo Modu", "OK",
                    "SensorSimulator.run_demo() mevcut",
                )
            else:
                return CheckResult(
                    "Demo Modu", "FAIL",
                    "SensorSimulator.run_demo() metodu bulunamadı",
                )
        except ImportError as exc:
            return CheckResult(
                "Demo Modu", "FAIL",
                f"Import hatası: {exc}",
            )

    def check_telegram_commands(self) -> CheckResult:
        """Telegram komut sistemi hazir mi?"""
        bot_token = self._config.telegram.bot_token
        if not bot_token:
            return CheckResult(
                "Telegram Komutları", "WARNING",
                "Bot token ayarlanmamış (komutlar devre dışı)",
            )

        try:
            import httpx
            resp = httpx.get(
                f"https://api.telegram.org/bot{bot_token}/getUpdates",
                params={"limit": 1, "timeout": 0},
                timeout=5.0,
            )
            if resp.status_code == 200:
                return CheckResult(
                    "Telegram Komutları", "OK",
                    "getUpdates erişilebilir, komut dinleme hazır",
                )
            else:
                return CheckResult(
                    "Telegram Komutları", "FAIL",
                    f"API hatası: {resp.status_code}",
                )
        except Exception as exc:
            return CheckResult(
                "Telegram Komutları", "FAIL",
                str(exc),
            )

    def run_all(self) -> list[CheckResult]:
        """Tum kontrolleri calistir."""
        checks = [
            self.check_config_sensors,
            self.check_mqtt_connection,
            self.check_sensor_events,
            self.check_telegram,
            self.check_telegram_commands,
            self.check_heartbeat,
            self.check_db_writable,
            self.check_dashboard,
            self.check_demo_mode_available,
            self.check_pet_situation,
        ]

        self._results = []
        for check_fn in checks:
            try:
                result = check_fn()
            except Exception as exc:
                result = CheckResult(check_fn.__name__, "FAIL", str(exc))
            self._results.append(result)

        return self._results

    def print_report(self) -> bool:
        """Sonuclari terminale yazdir.

        Returns:
            True = tum kontroller OK veya WARNING, False = en az 1 FAIL
        """
        # ANSI renk kodlari
        c_green = "\033[92m"
        c_yellow = "\033[93m"
        c_red = "\033[91m"
        c_reset = "\033[0m"
        c_bold = "\033[1m"

        status_colors = {
            "OK": c_green,
            "WARNING": c_yellow,
            "FAIL": c_red,
        }

        print(f"\n{c_bold}=== Annem Güvende - Pilot Checklist ==={c_reset}\n")

        ok_count = 0
        warn_count = 0
        fail_count = 0

        for r in self._results:
            color = status_colors.get(r.status, c_reset)
            status_pad = f"[{r.status}]".ljust(10)
            print(f"  {color}{status_pad}{c_reset} {r.name.ljust(20)} {r.message}")

            if r.status == "OK":
                ok_count += 1
            elif r.status == "WARNING":
                warn_count += 1
            else:
                fail_count += 1

        total = len(self._results)
        print(f"\n  Sonuç: {ok_count}/{total} OK", end="")
        if warn_count:
            print(f", {c_yellow}{warn_count} WARNING{c_reset}", end="")
        if fail_count:
            print(f", {c_red}{fail_count} FAIL{c_reset}", end="")
        print("\n")

        return fail_count == 0


def main():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Annem Güvende - Pilot öncesi sistem kontrolü"
    )
    parser.add_argument(
        "--config", default=None,
        help="Config dosya yolu (default: config.yml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    db_path = config.database.path

    checklist = PilotChecklist(config, db_path)
    checklist.run_all()
    all_ok = checklist.print_report()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
