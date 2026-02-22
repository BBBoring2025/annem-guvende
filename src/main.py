"""Annem Guvende - Ana giris noktasi.

FastAPI uygulamasi, lifespan ile MQTT client, APScheduler ve collector'u baslatir.
Tek proses: uvicorn entrypoint.
"""

import base64
import logging
import os
import secrets
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.alerter import AlertManager, TelegramNotifier
from src.collector import MQTTCollector
from src.config import load_config
from src.dashboard import dashboard_router
from src.database import (
    get_system_state,
    init_db,
    set_system_state,
)
from src.heartbeat import (
    HeartbeatClient,
    collect_system_metrics,
    run_health_checks,
)
from src.jobs import (
    daily_learning_job,
    daily_scoring_job,
    daily_summary_job,
    fill_yesterday_slots_job,
    heartbeat_job,
    mqtt_retry_job,
    nightly_maintenance_job,
    realtime_checks_job,
    slot_aggregation_job,
    telegram_command_job,
    watchdog_job,
)

# Loglama ayarlari
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("annem_guvende")

# Auth-free yollar (prefix match)
_AUTH_EXEMPT_PATHS = ("/health", "/docs", "/openapi.json")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth middleware.

    /health auth-free kalir. dashboard_username/password bos ise auth devre disi
    (geriye uyumluluk) ama WARNING basilir.
    """

    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self._username = username
        self._password = password
        self._enabled = bool(username and password)
        if not self._enabled:
            logger.warning(
                "Dashboard auth DEVRE DISI: config'te dashboard.username/password ayarlanmamis! "
                "Guvenlik riski - uretimde mutlaka ayarlayin."
            )

    async def dispatch(self, request: Request, call_next):
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        if path.startswith(_AUTH_EXEMPT_PATHS):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                req_user, req_pass = decoded.split(":", 1)
                if (
                    secrets.compare_digest(req_user, self._username)
                    and secrets.compare_digest(req_pass, self._password)
                ):
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Annem Guvende"'},
            content="Unauthorized",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yasam dongusu: baslangic ve kapanma islemleri."""

    # --- Baslangic (Startup) ---
    config = load_config()
    app.state.config = config
    logger.info("Konfigürasyon yuklendi")

    db_path = config.database.path

    # Veri dizini yazilabilirlik kontrolu
    db_dir = os.path.dirname(db_path) or "."
    if not os.access(db_dir, os.W_OK):
        logger.critical(
            "Veri dizini yazilabilir degil: %s — "
            "Docker volume izinlerini kontrol edin (bkz. docs/INSTALL.md).",
            db_dir,
        )
        raise SystemExit(1)

    init_db(db_path)
    app.state.db_path = db_path
    logger.info("Veritabani hazir: %s", db_path)

    # Dashboard guvenlik kontrolu
    if config.dashboard.password == "change_me_immediately":
        if os.environ.get("ANNEM_ENV") == "production":
            raise ValueError(
                "GUVENLIK: Production modda varsayilan sifre kullanilamaz! "
                "ANNEM_DASHBOARD_PASSWORD env variable veya config.yml guncelleyin."
            )
        logger.critical(
            "GUVENLIK UYARISI: Dashboard sifresi varsayilan degerde! "
            "config.yml veya ANNEM_DASHBOARD_PASSWORD env variable ile degistirin."
        )

    if os.environ.get("ANNEM_ENV") == "production":
        if not (config.dashboard.username and config.dashboard.password != "change_me_immediately"):
            raise ValueError(
                "GUVENLIK: Production modda dashboard username ve password ayarlanmali!"
            )

    # Tatil modu: DB'de state yoksa config degerini seed et
    if not get_system_state(db_path, "vacation_mode"):
        initial_vacation = str(config.system.vacation_mode).lower()
        set_system_state(db_path, "vacation_mode", initial_vacation)
        logger.info("Tatil modu baslatildi: %s", initial_vacation)

    # MQTT collector
    mqtt_collector = MQTTCollector(config, db_path)
    try:
        mqtt_collector.start()
        logger.info("MQTT collector baslatildi")
    except Exception as exc:
        logger.warning("MQTT baglantisi basarisiz, 30sn sonra tekrar denenir: %s", exc)
    app.state.mqtt_collector = mqtt_collector

    # APScheduler
    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("APScheduler baslatildi")

    # Telegram bildirim
    notifier = TelegramNotifier(
        bot_token=config.telegram.bot_token,
        chat_ids=config.telegram.chat_ids,
    )
    alert_mgr = AlertManager(config, notifier)
    app.state.alert_manager = alert_mgr
    logger.info("Bildirim sistemi hazir (enabled=%s)", notifier.enabled)

    # Pil uyari callback (notifier olusturulduktan sonra)
    def battery_alert_callback(warning: dict) -> None:
        from src.alerter.message_templates import render_battery_warning

        text = render_battery_warning(warning["sensor_id"], warning["battery"])
        notifier.send_to_all(text)

    mqtt_collector.set_battery_callback(battery_alert_callback)

    from src.learner.metrics import get_channels_from_config
    channels = get_channels_from_config(config)
    retention_days = config.database.retention_days

    # --- Scheduler Job'lari ---
    scheduler.add_job(
        lambda: slot_aggregation_job(db_path, channels),
        "cron", minute="0,15,30,45",
        id="slot_aggregator", name="15dk slot ozetleme", replace_existing=True,
    )
    scheduler.add_job(
        lambda: fill_yesterday_slots_job(db_path, channels),
        "cron", hour=0, minute=5,
        id="fill_missing_slots", name="Eksik slot doldurma", replace_existing=True,
    )
    scheduler.add_job(
        lambda: daily_learning_job(db_path, config),
        "cron", hour=0, minute=15,
        id="daily_learning", name="Gunluk model ogrenme", replace_existing=True,
    )
    scheduler.add_job(
        lambda: daily_scoring_job(db_path, config, alert_mgr),
        "cron", hour=0, minute=20,
        id="daily_scoring", name="Gunluk anomali skorlama", replace_existing=True,
    )
    scheduler.add_job(
        lambda: realtime_checks_job(db_path, config, alert_mgr),
        "cron", minute="0,30",
        id="realtime_checks", name="Gercek zamanli kontroller", replace_existing=True,
    )
    scheduler.add_job(
        lambda: daily_summary_job(db_path, config, alert_mgr),
        "cron", hour=22, minute=0,
        id="daily_summary", name="Gunluk ozet (22:00)", replace_existing=True,
    )

    # Heartbeat + Watchdog
    heartbeat_client = HeartbeatClient(
        url=config.heartbeat.url,
        device_id=config.heartbeat.device_id,
    )
    app.state.heartbeat_client = heartbeat_client

    if heartbeat_client.enabled:
        interval = config.heartbeat.interval_seconds
        scheduler.add_job(
            lambda: heartbeat_job(db_path, heartbeat_client, mqtt_collector),
            "interval", seconds=interval,
            id="heartbeat", name="Heartbeat (VPS ping)", replace_existing=True,
        )
        logger.info("Heartbeat aktif: %s (her %d sn)", config.heartbeat.url, interval)

    scheduler.add_job(
        lambda: watchdog_job(db_path, mqtt_collector, alert_mgr),
        "cron", minute="0,15,30,45",
        id="system_watchdog", name="Sistem saglik kontrolu", replace_existing=True,
    )
    logger.info("Sistem watchdog aktif (15dk araliklarla)")

    scheduler.add_job(
        lambda: mqtt_retry_job(mqtt_collector),
        "interval", seconds=30,
        id="mqtt_retry", name="MQTT yeniden baglanti", replace_existing=True,
    )

    scheduler.add_job(
        lambda: nightly_maintenance_job(db_path, retention_days),
        "cron", hour=3, minute=0,
        id="nightly_maintenance", name="Gece DB bakimi (03:00)", replace_existing=True,
    )
    logger.info("Gece bakimi aktif (03:00, retention=%d gun)", retention_days)

    # Telegram komut polling
    if notifier.enabled:
        scheduler.add_job(
            lambda: telegram_command_job(db_path, config, notifier),
            "interval", seconds=30,
            id="telegram_commands", name="Telegram komut isleme",
            misfire_grace_time=15, replace_existing=True,
        )
        logger.info("Telegram komut isleme aktif (30sn polling)")

    yield

    # --- Kapanma (Shutdown) ---
    mqtt_collector.stop()
    scheduler.shutdown(wait=False)
    notifier.close()
    logger.info("APScheduler durduruldu")
    logger.info("Uygulama kapaniyor")


app = FastAPI(
    title="Annem Guvende",
    description="Yasli bireyler icin sensor tabanli rutin ogrenme ve anomali tespit sistemi",
    version="0.1.0",
    lifespan=lifespan,
)

_boot_config = load_config()
app.add_middleware(
    BasicAuthMiddleware,
    username=_boot_config.dashboard.username,
    password=_boot_config.dashboard.password,
)

app.include_router(dashboard_router)


@app.get("/")
async def root_redirect():
    """Ana sayfa -> dashboard yonlendirmesi."""
    return RedirectResponse(url="/static/index.html")


@app.get("/health")
async def health_check(response: Response):
    """Sistem saglik kontrolu endpoint'i."""
    try:
        metrics = collect_system_metrics(app.state.db_path)
        mqtt_ok = app.state.mqtt_collector.is_connected()
        status = run_health_checks(metrics, mqtt_ok)
        return {
            "status": "ok" if status.all_healthy else "degraded",
            "version": "0.1.0",
            "checks": {c.name: c.healthy for c in status.checks},
            "metrics": {
                "cpu_percent": metrics.cpu_percent,
                "memory_percent": metrics.memory_percent,
                "disk_percent": metrics.disk_percent,
                "cpu_temp": metrics.cpu_temp,
                "db_size_mb": round(metrics.db_size_mb, 2),
                "today_event_count": metrics.today_event_count,
            },
        }
    except Exception as exc:
        response.status_code = 503
        return {"status": "error", "reason": str(exc), "version": "0.1.0"}


_static_dir = os.path.join(os.path.dirname(__file__), "dashboard", "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8099, reload=False)
