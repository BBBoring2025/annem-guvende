"""Demo modu CLI entrypoint.

Kullanim:
    python -m src.simulator --demo
    python -m src.simulator --demo --speed 1
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta

from src.collector.slot_aggregator import aggregate_current_slot, fill_missing_slots
from src.config import load_config
from src.database import init_db
from src.detector import run_daily_scoring
from src.learner import run_daily_learning
from src.learner.metrics import DEFAULT_CHANNELS, get_channels_from_config
from src.simulator.sensor_simulator import SensorSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("annem_guvende.simulator")


def demo_day_callback(day_num: int, date: str, event_count: int, is_anomaly: bool) -> None:
    """Her gun sonunda terminale ilerleme yazdir."""
    marker = "ANOMALI" if is_anomaly else "Normal"
    phase = "Ogrenme" if day_num <= 14 else "Test"
    print(f"  Gun {day_num:2d}/21 | {date} | {event_count:3d} event | {phase} | {marker}")


def run_demo_with_pipeline(config_path: str | None, speed: float) -> None:
    """Demo simulasyonu tam pipeline ile calistir."""
    config = load_config(config_path)
    db_path = config.database.path
    init_db(db_path)

    channels = get_channels_from_config(config)
    if not channels:
        channels = list(DEFAULT_CHANNELS)

    sim = SensorSimulator(db_path, seed=42)

    print("\n=== Annem Guvende - Demo Modu ===\n")
    print(f"Veritabani: {db_path}")
    print(f"Kanallar: {', '.join(channels)}")
    print(f"Hiz: {speed} sn/gun\n")

    def pipeline_callback(day_num: int, date: str, event_count: int, is_anomaly: bool) -> None:
        """Her gun: slot aggregation + fill + learn + score."""
        demo_day_callback(day_num, date, event_count, is_anomaly)

        # Slot aggregation: o gunun tum 96 slotunu doldur
        base = datetime.strptime(date, "%Y-%m-%d")
        for slot_idx in range(96):
            slot_time = base + timedelta(minutes=slot_idx * 15)
            aggregate_current_slot(db_path, channels, now=slot_time)
        fill_missing_slots(db_path, date, channels)

        # Ogrenme + skorlama
        run_daily_learning(db_path, config, target_date=date)
        run_daily_scoring(db_path, config)

    result = sim.run_demo(
        start_date="2025-01-01",
        days=21,
        day_duration_seconds=speed,
        callback=pipeline_callback,
    )

    print("\n--- Sonuc ---")
    print(f"Toplam event: {result['total_events']}")
    print(f"Anomali tarihi: {result['anomaly_date']} ({result['anomaly_type']})")
    print("Demo tamamlandi.\n")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Annem Guvende - Sensor Simulator")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Demo modunu calistir (21 gun hizlandirilmis simulasyon)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=3.0,
        help="Gunler arasi bekleme suresi (saniye, default=3.0)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Config dosya yolu",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo_with_pipeline(args.config, args.speed)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
