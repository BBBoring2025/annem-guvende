"""Zamanlayici job fonksiyonlari.

main.py lifespan'dan cikarilmis 10 job. Her biri explicit parametre alir,
closure yerine fonksiyon olarak tanimlanir. main.py lambda wrapper ile cagirir.
"""

import logging
from datetime import datetime, timedelta

from src.alerter import AlertManager, TelegramNotifier
from src.collector.mqtt_client import MQTTCollector
from src.collector.slot_aggregator import aggregate_current_slot, fill_missing_slots
from src.config import AppConfig
from src.database import (
    cleanup_old_events,
    get_db,
    is_vacation_mode,
    run_db_maintenance,
)
from src.detector import run_daily_scoring, run_realtime_checks
from src.heartbeat import (
    HeartbeatClient,
    collect_system_metrics,
    format_watchdog_alert,
    run_health_checks,
)
from src.learner import run_daily_learning

logger = logging.getLogger("annem_guvende")


def slot_aggregation_job(db_path: str, channels: list[str]) -> None:
    """15dk slot ozetleme (saat dilimlerine hizali)."""
    adjusted_now = datetime.now() - timedelta(minutes=1)
    aggregate_current_slot(db_path, channels, now=adjusted_now)


def fill_yesterday_slots_job(db_path: str, channels: list[str]) -> None:
    """Onceki gunun eksik slotlarini doldur."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    fill_missing_slots(db_path, yesterday, channels)


def daily_learning_job(db_path: str, config: AppConfig) -> None:
    """Gunluk model ogrenme (tatil modunda atlanir)."""
    if is_vacation_mode(db_path, config):
        logger.info("Tatil modu aktif - gunluk ogrenme atlaniyor")
        return
    run_daily_learning(db_path, config)


def daily_scoring_job(
    db_path: str, config: AppConfig, alert_mgr: AlertManager
) -> None:
    """Gunluk anomali skorlama + alarm + milestone (tatil modunda atlanir)."""
    if is_vacation_mode(db_path, config):
        logger.info("Tatil modu aktif - gunluk skorlama atlaniyor")
        return
    run_daily_scoring(db_path, config)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    alert_mgr.handle_daily_scores(db_path, yesterday)
    alert_mgr.handle_learning_milestone(db_path)


def realtime_checks_job(
    db_path: str, config: AppConfig, alert_mgr: AlertManager
) -> None:
    """Gercek zamanli sessizlik kontrolleri (tatil modunda atlanir)."""
    if is_vacation_mode(db_path, config):
        return
    alerts = run_realtime_checks(db_path, config)
    for alert in alerts:
        logger.warning(
            "Gercek zamanli alarm: %s | seviye=%d | %s",
            alert.alert_type, alert.alert_level, alert.message,
        )
        alert_mgr.handle_realtime_alert(alert, db_path=db_path)


def daily_summary_job(
    db_path: str, config: AppConfig, alert_mgr: AlertManager
) -> None:
    """Gunluk ozet mesaji (tatil modunda atlanir)."""
    if is_vacation_mode(db_path, config):
        logger.info("Tatil modu aktif - gunluk ozet atlaniyor")
        return
    alert_mgr.handle_daily_summary(db_path)


def heartbeat_job(
    db_path: str,
    heartbeat_client: HeartbeatClient,
    mqtt_collector: MQTTCollector,
) -> None:
    """Heartbeat VPS ping."""
    metrics = collect_system_metrics(db_path)
    heartbeat_client.send(metrics, mqtt_collector.is_connected())


def watchdog_job(
    db_path: str,
    mqtt_collector: MQTTCollector,
    alert_mgr: AlertManager,
) -> None:
    """Sistem saglik kontrolu."""
    metrics = collect_system_metrics(db_path)
    status = run_health_checks(metrics, mqtt_collector.is_connected())
    if not status.all_healthy:
        for w in status.warnings:
            logger.warning("Watchdog: %s - %s", w.name, w.message)
        alert_text = format_watchdog_alert(status)
        if alert_text:
            alert_mgr.send_notification(alert_text)


def mqtt_retry_job(mqtt_collector: MQTTCollector) -> None:
    """MQTT yeniden baglanti denemesi."""
    if not mqtt_collector.is_connected():
        try:
            mqtt_collector.start()
            logger.info("MQTT yeniden baglandi")
        except Exception as exc:
            logger.warning("MQTT yeniden baglanti basarisiz: %s", exc)


def _cleanup_old_pending_alerts(db_path: str, days: int = 30) -> int:
    """30 gunden eski pending_alerts kayitlarini sil.

    Args:
        db_path: Veritabani yolu
        days: Saklama suresi (gun)

    Returns:
        Silinen kayit sayisi
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM pending_alerts WHERE timestamp < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        conn.commit()
    if deleted:
        logger.info("Eski pending_alerts temizlendi: %d kayit", deleted)
    return deleted


def nightly_maintenance_job(db_path: str, retention_days: int) -> None:
    """Gece DB bakimi: eski eventleri temizle + pending_alerts temizle + WAL checkpoint."""
    try:
        deleted = cleanup_old_events(db_path, retention_days)
        pa_deleted = _cleanup_old_pending_alerts(db_path, days=30)
        run_db_maintenance(db_path)
        logger.info(
            "Gece bakimi tamamlandi: %d eski event, %d eski pending_alert silindi",
            deleted, pa_deleted,
        )
    except Exception as exc:
        logger.error("Gece bakimi hatasi: %s", exc)


def weekly_trend_job(
    db_path: str, config: AppConfig, alert_mgr: AlertManager
) -> None:
    """Pazar 10:00 — haftalik kirilganlik trend raporu."""
    from src.detector.trend_analyzer import analyze_all_trends
    from src.learner.metrics import get_channels_from_config

    channels = get_channels_from_config(config)
    trends = analyze_all_trends(
        db_path, channels,
        config.system.trend_analysis_days,
        config.system.trend_min_days,
    )

    messages: list[str] = []
    bath_trend = trends.get("bathroom")
    if bath_trend is not None and bath_trend > config.system.trend_bathroom_threshold:
        messages.append(
            f"📈 Son {config.system.trend_analysis_days} günde banyo kullanım "
            f"sıklığında artış trendi var (eğim: +{bath_trend:.2f}). "
            f"İdrar yolu enfeksiyonu veya sindirim sorunu habercisi olabilir."
        )

    pres_trend = trends.get("presence")
    if pres_trend is not None and pres_trend < config.system.trend_presence_threshold:
        messages.append(
            f"📉 Son {config.system.trend_analysis_days} günde genel ev içi "
            f"hareketlilikte azalma trendi var (eğim: {pres_trend:.2f}). "
            f"Yorgunluk veya motivasyon düşüklüğü habercisi olabilir."
        )

    if messages:
        header = "🏥 <b>Haftalık Kırılganlık Raporu</b>\n\n"
        full_msg = header + "\n\n".join(messages)
        alert_mgr.send_notification(full_msg)
        logger.info("Haftalik kirilganlik raporu gonderildi: %d mesaj", len(messages))
    else:
        logger.info("Haftalik kirilganlik raporu: trend normal, bildirim yok")


def escalation_check_job(
    db_path: str, config: AppConfig, notifier: TelegramNotifier
) -> None:
    """Her 2 dakikada bir: yanitsiz acil alarmlari kontrol et.

    pending_alerts tablosunda status='pending' ve suresi dolmus kayitlari
    bulur, emergency_chat_ids'e eskalasyon mesaji gonderir.
    """
    from src.database import get_db

    timeout = config.telegram.escalation_minutes
    emergency_ids = config.telegram.emergency_chat_ids

    if not emergency_ids:
        return  # Eskalasyon kisisi tanimli degilse atla

    cutoff = (datetime.now() - timedelta(minutes=timeout)).isoformat()

    with get_db(db_path) as conn:
        expired = conn.execute(
            "SELECT id, message FROM pending_alerts "
            "WHERE status = 'pending' AND timestamp <= ?",
            (cutoff,),
        ).fetchall()

        for alert in expired:
            esc_msg = (
                "🚨 <b>ACİL ESKALASYON</b>\n\n"
                "Ana kullanıcı acil durum mesajına "
                f"{timeout} dakikadır yanıt vermedi!\n\n"
                f"Orijinal alarm:\n{alert['message']}\n\n"
                "Lütfen yaşlı bireyi kontrol edin!"
            )
            for eid in emergency_ids:
                notifier.send_message(eid, esc_msg)

            conn.execute(
                "UPDATE pending_alerts SET status = 'escalated' WHERE id = ?",
                (alert["id"],),
            )
            logger.warning(
                "Eskalasyon gonderildi: alert_id=%d, %d emergency kisi",
                alert["id"], len(emergency_ids),
            )

        conn.commit()


def telegram_command_job(db_path: str, config: AppConfig, notifier) -> None:
    """Telegram komutlarini isle (30sn polling)."""
    try:
        notifier.process_commands(db_path, config)
    except Exception as exc:
        logger.error("Telegram komut isleme hatasi: %s", exc)
