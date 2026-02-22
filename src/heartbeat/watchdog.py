"""Servis saglik kontrolu ve esik degerlendirmesi.

Saf fonksiyonlar: SystemMetrics alir, HealthStatus dondurur.
Hicbir side effect yok, DB erisimi yok, psutil cagrisi yok.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from src.heartbeat.system_monitor import SystemMetrics

logger = logging.getLogger("annem_guvende.heartbeat")


# --- Esik sabitleri ---
CPU_TEMP_WARNING = 80.0  # Celsius
DISK_WARNING_PERCENT = 90.0
RAM_WARNING_PERCENT = 85.0
DB_SIZE_WARNING_MB = 500.0  # Pi icin buyuk


@dataclass
class HealthCheck:
    """Tek bir saglik kontrolu sonucu."""

    name: str
    healthy: bool
    message: str


@dataclass
class HealthStatus:
    """Tum sistem saglik durumu."""

    checks: list[HealthCheck] = field(default_factory=list)
    timestamp: str = ""

    @property
    def all_healthy(self) -> bool:
        """Tum kontroller saglikli mi?"""
        return all(c.healthy for c in self.checks)

    @property
    def warnings(self) -> list[HealthCheck]:
        """Sagliksiz kontrollerin listesi."""
        return [c for c in self.checks if not c.healthy]


def check_cpu_temp(metrics: SystemMetrics) -> HealthCheck:
    """CPU sicakligi kontrolu.

    > 80°C → sagliksiz.
    None (Pi olmayan platform) → saglikli.
    """
    if metrics.cpu_temp is None:
        return HealthCheck(
            name="cpu_temp",
            healthy=True,
            message="CPU sıcaklık sensörü mevcut değil.",
        )

    if metrics.cpu_temp >= CPU_TEMP_WARNING:
        return HealthCheck(
            name="cpu_temp",
            healthy=False,
            message=f"CPU sıcaklığı çok yüksek: {metrics.cpu_temp:.1f}°C",
        )

    return HealthCheck(
        name="cpu_temp",
        healthy=True,
        message=f"CPU sıcaklığı normal: {metrics.cpu_temp:.1f}°C",
    )


def check_disk_usage(metrics: SystemMetrics) -> HealthCheck:
    """Disk kullanim kontrolu.

    > %90 → sagliksiz.
    """
    if metrics.disk_percent >= DISK_WARNING_PERCENT:
        return HealthCheck(
            name="disk",
            healthy=False,
            message=f"Disk kullanımı çok yüksek: %{metrics.disk_percent:.0f}",
        )

    return HealthCheck(
        name="disk",
        healthy=True,
        message=f"Disk kullanımı normal: %{metrics.disk_percent:.0f}",
    )


def check_ram_usage(metrics: SystemMetrics) -> HealthCheck:
    """RAM kullanim kontrolu.

    > %85 → sagliksiz.
    """
    if metrics.memory_percent >= RAM_WARNING_PERCENT:
        return HealthCheck(
            name="ram",
            healthy=False,
            message=f"RAM kullanımı çok yüksek: %{metrics.memory_percent:.0f}",
        )

    return HealthCheck(
        name="ram",
        healthy=True,
        message=f"RAM kullanımı normal: %{metrics.memory_percent:.0f}",
    )


def check_mqtt_status(
    mqtt_connected: bool,
    last_event_age_minutes: float | None,
) -> HealthCheck:
    """MQTT baglanti kontrolu.

    Baglanti kopuk → sagliksiz.

    NOT: 'Son event > 3h' kontrolu realtime_checks.py'de.
    Burada sadece MQTT baglanti durumu kontrol edilir.
    """
    if not mqtt_connected:
        return HealthCheck(
            name="mqtt",
            healthy=False,
            message="MQTT bağlantısı kopuk!",
        )

    return HealthCheck(
        name="mqtt",
        healthy=True,
        message="MQTT bağlantısı aktif.",
    )


def check_db_health(db_size_mb: float) -> HealthCheck:
    """Veritabani saglik kontrolu.

    > 500 MB → uyari (Pi icin buyuk).
    """
    if db_size_mb >= DB_SIZE_WARNING_MB:
        return HealthCheck(
            name="database",
            healthy=False,
            message=f"Veritabanı çok büyük: {db_size_mb:.1f} MB",
        )

    return HealthCheck(
        name="database",
        healthy=True,
        message=f"Veritabanı boyutu normal: {db_size_mb:.1f} MB",
    )


def run_health_checks(
    metrics: SystemMetrics,
    mqtt_connected: bool,
    now: datetime | None = None,
) -> HealthStatus:
    """Tum saglik kontrollerini calistir.

    Saf fonksiyon: SystemMetrics + mqtt_connected alir,
    HealthStatus dondurur.

    Args:
        metrics: Sistem metrikleri
        mqtt_connected: MQTT baglanti durumu
        now: Simdiki zaman (test icin override)

    Returns:
        HealthStatus (tum check sonuclari)
    """
    if now is None:
        now = datetime.now()

    checks = [
        check_cpu_temp(metrics),
        check_disk_usage(metrics),
        check_ram_usage(metrics),
        check_mqtt_status(mqtt_connected, metrics.last_event_age_minutes),
        check_db_health(metrics.db_size_mb),
    ]

    return HealthStatus(
        checks=checks,
        timestamp=now.isoformat(),
    )


def format_watchdog_alert(status: HealthStatus) -> str | None:
    """Sagliksiz kontroller icin Turkce uyari mesaji olustur.

    Tum kontroller saglikliysa None dondurur.

    Args:
        status: HealthStatus sonucu

    Returns:
        Turkce HTML mesaj veya None
    """
    if status.all_healthy:
        return None

    warnings = status.warnings
    if not warnings:
        return None

    lines = ["⚙️ <b>Sistem Sağlık Uyarısı</b>\n"]

    has_mqtt_warning = False
    for w in warnings:
        lines.append(f"⚠️ {w.message}")
        if w.name == "mqtt":
            has_mqtt_warning = True

    if has_mqtt_warning:
        lines.append(
            "\n💡 Bu durum bir internet kesintisinden de kaynaklanıyor olabilir."
        )

    lines.append("\nℹ️ Lütfen sistemi kontrol edin.")

    return "\n".join(lines)
