"""Typed konfigürasyon - Pydantic modelleri.

YAML dosyasindan yuklenen ayarlar AppConfig modeline dönüstürülür.
Tüm config.get() erisimi attribute erisimi ile degistirilir.
"""

import logging
import os

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger("annem_guvende")

# Varsayilan config dosya yolu
_DEFAULT_CONFIG_PATH = "config.yml"
_FALLBACK_CONFIG_PATH = "config.yml.example"


class MqttConfig(BaseModel):
    broker: str = "localhost"
    port: int = 1883
    topic_prefix: str = "zigbee2mqtt"


class SensorConfig(BaseModel):
    id: str = ""
    channel: str = ""
    type: str = ""
    trigger_value: str = ""


class ModelConfig(BaseModel):
    slot_minutes: int = 15
    awake_start_hour: int = 6
    awake_end_hour: int = 23
    learning_days: int = 14
    prior_alpha: float = 1.0
    prior_beta: float = 1.0


class AlertsConfig(BaseModel):
    z_threshold_gentle: float = 2.0
    z_threshold_serious: float = 3.0
    z_threshold_emergency: float = 4.0
    min_train_days: int = 7
    morning_check_hour: int = 11
    silence_threshold_hours: int = 3
    fall_detection_minutes: int = 45  # 0 ise ozellik kapali


class TelegramConfig(BaseModel):
    bot_token: str = ""
    chat_ids: list[str] = Field(default_factory=list)
    emergency_chat_ids: list[str] = Field(default_factory=list)
    escalation_minutes: int = 10


class HeartbeatConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    device_id: str = "annem-pi"
    interval_seconds: int = 300


class DatabaseConfig(BaseModel):
    path: str = "./data/annem_guvende.db"
    retention_days: int = 90


class DashboardConfig(BaseModel):
    username: str = ""
    password: str = ""


class SystemConfig(BaseModel):
    vacation_mode: bool = False
    trend_analysis_days: int = 30
    trend_min_days: int = 14
    trend_bathroom_threshold: float = 0.3
    trend_presence_threshold: float = -0.3


class AppConfig(BaseModel):
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    sensors: list[SensorConfig] = Field(default_factory=list)
    model: ModelConfig = Field(default_factory=ModelConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)


def load_config(path: str | None = None) -> AppConfig:
    """Konfigürasyon dosyasini yukle ve AppConfig olarak dondur.

    Arama sirasi:
    1. Verilen path parametresi
    2. ANNEM_CONFIG_PATH cevre degiskeni
    3. config.yml (calisma dizininde)
    4. config.yml.example (fallback)
    """
    if path is None:
        path = os.environ.get("ANNEM_CONFIG_PATH", _DEFAULT_CONFIG_PATH)

    if not os.path.exists(path):
        logger.warning(
            "Config dosyasi bulunamadi: %s, fallback kullaniliyor: %s",
            path,
            _FALLBACK_CONFIG_PATH,
        )
        path = _FALLBACK_CONFIG_PATH

    if not os.path.exists(path):
        logger.warning("Fallback config de bulunamadi, default config kullaniliyor")
        return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    config = AppConfig(**raw)

    # Env variable override (Docker secrets icin)
    env_password = os.environ.get("ANNEM_DASHBOARD_PASSWORD")
    if env_password:
        config.dashboard.password = env_password
    env_username = os.environ.get("ANNEM_DASHBOARD_USERNAME")
    if env_username:
        config.dashboard.username = env_username
    env_token = os.environ.get("ANNEM_TELEGRAM_BOT_TOKEN")
    if env_token:
        config.telegram.bot_token = env_token
    env_db_path = os.environ.get("ANNEM_DB_PATH")
    if env_db_path:
        config.database.path = env_db_path

    logger.info("Config yuklendi: %s", path)
    return config
