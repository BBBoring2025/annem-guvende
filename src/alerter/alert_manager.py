"""Alert Manager - Karar motoru, rate limiting, aciklama uretimi.

Detector sonuclarini alir, kurallara gore filtreleyip
uygun mesajlari TelegramNotifier ile gonderir.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.alerter.message_templates import (
    render_alert,
    render_daily_summary,
    render_learning_complete,
    render_learning_progress,
    render_morning_silence,
)
from src.alerter.telegram_bot import TelegramNotifier
from src.config import AppConfig
from src.database import get_db, get_system_state, set_system_state
from src.detector.realtime_checks import RealtimeAlert

logger = logging.getLogger("annem_guvende.alerter")

# Kanal etiketleri (Turkce)
CHANNEL_LABELS = {
    "presence": "Hareket sensörü",
    "fridge": "Buzdolabı",
    "bathroom": "Banyo",
    "door": "Kapı",
}


class AlertManager:
    """Bildirim karar motoru.

    Rate limiting, ogrenme donemi filtreleri ve
    aciklama uretimi burada yapilir.

    Args:
        config: Uygulama konfigurasyonu
        notifier: TelegramNotifier instance
    """

    def __init__(self, config: AppConfig, notifier: TelegramNotifier):
        self._config = config
        self._notifier = notifier

        # Rate limiting: {alert_level: datetime} son gonderim zamani
        self._last_alert_time: dict[int, datetime] = {}
        # Sabah alarm sayaci: {date_str: int}
        self._morning_alert_count: dict[str, int] = {}

        # Rate limiting parametreleri
        self._cooldown_hours = 6
        self._morning_max_per_day = 2

    # ------------------------------------------------------------------ #
    #  Rate Limiting
    # ------------------------------------------------------------------ #

    def _load_rate_state_from_db(self, db_path: str) -> None:
        """DB'den rate-limit state'i yukle (soguk baslangic icin)."""
        raw = get_system_state(db_path, "alert_rate_state", "")
        if not raw:
            return
        try:
            # Format: "level:iso_timestamp;level:iso_timestamp;..."
            for pair in raw.split(";"):
                if ":" not in pair:
                    continue
                lvl_str, ts_str = pair.split(":", 1)
                self._last_alert_time[int(lvl_str)] = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            logger.warning("DB'deki rate-limit state parse edilemedi, sifirlanacak")

    def _save_rate_state_to_db(self, db_path: str) -> None:
        """Rate-limit state'i DB'ye kaydet."""
        parts = [
            f"{lvl}:{ts.isoformat()}"
            for lvl, ts in self._last_alert_time.items()
        ]
        set_system_state(db_path, "alert_rate_state", ";".join(parts))

    def should_send_alert(
        self,
        alert_level: int,
        train_days: int,
        now: datetime | None = None,
        db_path: str | None = None,
    ) -> bool:
        """Bu alarm gonderilmeli mi?

        Kurallar:
        1. Gun 1-7: alarm yok
        2. Gun 8-14: max seviye 1
        3. Gun 15+: tum seviyeler
        4. Ayni seviye 6 saat icinde tekrar gonderilmez
        5. Seviye yukseldiyse her zaman gonder

        Args:
            alert_level: 0-3 (0 = alarm yok)
            train_days: Egitim gun sayisi
            now: Simdiki zaman (test icin override)
            db_path: Veritabani yolu (state kaliciligi icin)

        Returns:
            True ise alarm gonder
        """
        if alert_level <= 0:
            return False

        if now is None:
            now = datetime.now()

        # Ogrenme donemi kisitlamalari
        if train_days < 7:
            return False
        if train_days < 15 and alert_level > 1:
            return False

        # DB'den yukle (RAM cache bossa ve db_path varsa)
        if not self._last_alert_time and db_path:
            self._load_rate_state_from_db(db_path)

        # Seviye yukselmesi kontrolu: onceki seviyelere bak
        last_max_level = max(self._last_alert_time.keys(), default=0)
        if alert_level > last_max_level and last_max_level > 0:
            # Seviye yukseldi -> her zaman gonder
            self._last_alert_time[alert_level] = now
            if db_path:
                self._save_rate_state_to_db(db_path)
            return True

        # Ayni seviye cooldown kontrolu
        last_time = self._last_alert_time.get(alert_level)
        if last_time is not None:
            elapsed = now - last_time
            if elapsed < timedelta(hours=self._cooldown_hours):
                return False

        self._last_alert_time[alert_level] = now
        if db_path:
            self._save_rate_state_to_db(db_path)
        return True

    def should_send_morning(
        self,
        date: str,
        now: datetime | None = None,
    ) -> bool:
        """Sabah sessizlik alarmi gonderilmeli mi?

        Gunde max 2 kez.

        Args:
            date: YYYY-MM-DD
            now: Simdiki zaman (test icin)

        Returns:
            True ise gonder
        """
        if now is None:
            now = datetime.now()

        count = self._morning_alert_count.get(date, 0)
        if count >= self._morning_max_per_day:
            return False

        self._morning_alert_count[date] = count + 1
        return True

    # ------------------------------------------------------------------ #
    #  Aciklama Uretimi
    # ------------------------------------------------------------------ #

    def generate_explanation(self, db_path: str, date: str) -> str:
        """Anomali icin insan-okunur aciklama uret.

        Per-channel NLL degerlerini tarihsel ortalama ile karsilastirir.
        Oran > 1.5x ise kanal anomal olarak isaretlenir.
        count_z < -2.0 ise dusuk aktivite aciklamasi eklenir.

        Args:
            db_path: Veritabani yolu
            date: Hedef tarih

        Returns:
            Turkce aciklama metni
        """
        with get_db(db_path) as conn:
            # Hedef gun verileri
            row = conn.execute(
                """SELECT nll_presence, nll_fridge, nll_bathroom, nll_door,
                          count_z, observed_count, expected_count
                   FROM daily_scores WHERE date = ?""",
                (date,),
            ).fetchone()

            if row is None:
                return "Detaylı bilgi mevcut değil."

            # Tarihsel normal gunlerin per-channel NLL ortalamalari
            history = conn.execute(
                """SELECT
                    AVG(nll_presence) as avg_presence,
                    AVG(nll_fridge) as avg_fridge,
                    AVG(nll_bathroom) as avg_bathroom,
                    AVG(nll_door) as avg_door,
                    COUNT(*) as n
                   FROM daily_scores
                   WHERE alert_level = 0 AND is_learning = 0
                     AND date != ?""",
                (date,),
            ).fetchone()

        # Yeterli tarihce yoksa basit aciklama
        if history is None or history["n"] < 3:
            return "Henüz yeterli veri yok, detaylı analiz yapılamıyor."

        explanations = []

        # Per-channel analiz
        channels = {
            "presence": (row["nll_presence"], history["avg_presence"]),
            "fridge": (row["nll_fridge"], history["avg_fridge"]),
            "bathroom": (row["nll_bathroom"], history["avg_bathroom"]),
            "door": (row["nll_door"], history["avg_door"]),
        }

        for ch, (today_nll, avg_nll) in channels.items():
            if today_nll is None or avg_nll is None or avg_nll == 0:
                continue
            ratio = today_nll / avg_nll
            if ratio > 1.5:
                label = CHANNEL_LABELS.get(ch, ch)
                explanations.append(
                    f"{label} aktivitesi beklenenden çok düşük."
                )

        # Dusuk toplam aktivite
        count_z = row["count_z"]
        if count_z is not None and count_z < -2.0:
            observed = row["observed_count"] or 0
            expected = row["expected_count"] or 0
            explanations.append(
                f"Toplam aktivite çok düşük "
                f"({observed} olay, beklenen: ~{expected:.0f})."
            )

        if not explanations:
            return "Genel aktivite örüntüsü normalden farklı."

        return "\n".join(explanations)

    # ------------------------------------------------------------------ #
    #  Ana Isleyiciler
    # ------------------------------------------------------------------ #

    def handle_daily_scores(self, db_path: str, date: str) -> None:
        """Gunluk skorlama sonrasi alarm kontrolu.

        00:20'de daily_scoring_job tarafindan cagirilir.

        Args:
            db_path: Veritabani yolu
            date: Degerlendirilen tarih (genellikle dun)
        """
        with get_db(db_path) as conn:
            row = conn.execute(
                """SELECT composite_z, alert_level, train_days, is_learning
                   FROM daily_scores WHERE date = ?""",
                (date,),
            ).fetchone()

        if row is None:
            return

        alert_level = row["alert_level"]
        train_days = row["train_days"] or 0

        if alert_level > 0 and self.should_send_alert(alert_level, train_days, db_path=db_path):
            explanation = self.generate_explanation(db_path, date)
            text = render_alert(
                level=alert_level,
                date=date,
                composite_z=row["composite_z"],
                explanation=explanation,
            )
            if text:
                self._notifier.send_to_all(text)
                logger.info(
                    "Alarm gonderildi: date=%s level=%d", date, alert_level
                )

    def handle_realtime_alert(self, alert: RealtimeAlert, db_path: str | None = None) -> None:
        """Gercek zamanli alarm isleyici.

        Her 30dk realtime_checks_job tarafindan cagirilir.

        Args:
            alert: Gercek zamanli alarm verisi
            db_path: Veritabani yolu (rate-limit state kaliciligi icin)
        """
        if alert.alert_type == "morning_silence":
            today = datetime.now().strftime("%Y-%m-%d")
            if self.should_send_morning(today):
                now_str = datetime.now().strftime("%H:%M")
                text = render_morning_silence(check_time=now_str)
                self._notifier.send_to_all(text)
                logger.info("Sabah sessizlik alarmi gonderildi")
        elif alert.alert_type == "extended_silence":
            # Extended silence icin genel rate limiting kullan
            if self.should_send_alert(
                alert.alert_level, train_days=15, db_path=db_path
            ):
                text = (
                    f"⏰ <b>Uzun Sessizlik</b>\n\n"
                    f"{alert.message}\n\n"
                    f"📞 Lütfen kontrol edin."
                )
                self._notifier.send_to_all(text)
                logger.info("Uzun sessizlik alarmi gonderildi")

    def handle_daily_summary(self, db_path: str) -> None:
        """22:00 gunluk ozet gondericisi.

        Args:
            db_path: Veritabani yolu
        """
        today = datetime.now().strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            # Gunun skorlari
            row = conn.execute(
                """SELECT composite_z, alert_level, train_days
                   FROM daily_scores WHERE date = ?""",
                (today,),
            ).fetchone()

            # Gunun event sayilari (channel bazli)
            events = conn.execute(
                """SELECT channel, COUNT(*) as cnt
                   FROM sensor_events
                   WHERE timestamp >= ? AND timestamp < ?
                   GROUP BY channel""",
                (f"{today}T00:00:00", f"{today}T23:59:59"),
            ).fetchall()

            # Model state'ten gercek CI width hesapla
            models = conn.execute(
                "SELECT alpha, beta FROM model_state"
            ).fetchall()

        # Skor varsa
        if row is not None:
            composite_z = row["composite_z"] or 0.0
            alert_level = row["alert_level"] or 0
            train_days = row["train_days"] or 0
        else:
            composite_z = 0.0
            alert_level = 0
            train_days = 0

        # Event sayilari dict
        event_counts = {e["channel"]: e["cnt"] for e in events} if events else {}

        # CI width: model_state varsa gercek posterior'dan hesapla, yoksa fallback
        if models:
            from src.learner.beta_model import BetaPosterior
            ci_width = sum(
                BetaPosterior(r["alpha"], r["beta"]).ci_width for r in models
            ) / len(models)
        else:
            ci_width = max(0.05, 1.0 / max(train_days, 1))

        text = render_daily_summary(
            date=today,
            composite_z=composite_z,
            alert_level=alert_level,
            train_days=train_days,
            ci_width=ci_width,
            event_counts=event_counts,
        )
        self._notifier.send_to_all(text)
        logger.info("Günlük özet gönderildi: %s", today)

    def handle_learning_milestone(self, db_path: str) -> None:
        """Ogrenme donemi kilometre tasi bildirimleri.

        00:20'de daily_scoring_job tarafindan cagirilir.
        train_days == 7 veya 14 ise bildirim gonder.

        Args:
            db_path: Veritabani yolu
        """
        # En son daily_scores'tan train_days'i al
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT train_days FROM daily_scores WHERE date = ?",
                (yesterday,),
            ).fetchone()

        if row is None:
            return

        train_days = row["train_days"] or 0

        if train_days == 7:
            ci_width = 1.0 / 7
            text = render_learning_progress(
                date=yesterday,
                train_days=7,
                ci_width=ci_width,
                extra_message="İlk hafta tamamlandı! Basit alarmlar artık aktif.",
            )
            self._notifier.send_to_all(text)
            logger.info("Öğrenme kilometre taşı: 7. gün")

        elif train_days == 14:
            confidence = 85.0  # MVP icin sabit
            text = render_learning_complete(confidence=confidence)
            self._notifier.send_to_all(text)
            logger.info("Öğrenme tamamlandı: 14. gün")
