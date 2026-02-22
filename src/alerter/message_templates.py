"""Turkce mesaj sablonlari ve render fonksiyonlari.

Saf fonksiyonlar: DB erisimi yok, girdi alir, string dondurur.
HTML parse_mode ile Telegram'a gonderilmek uzere formatlanir.
"""

# --- Sablonlar ---

TEMPLATE_DAILY_SUMMARY = (
    "🏠 <b>Günlük Özet</b> — {date}\n\n"
    "{status}\n\n"
    "📊 Anomali skoru: <b>{composite_z:.1f}</b>\n"
    "📈 Güven aralığı: ±{ci_pct:.0f}%\n"
    "🔢 Toplam olay: {total_events}\n"
    "{channel_lines}\n"
    "🧠 Eğitim: {train_days}. gün"
)

TEMPLATE_ALERT_GENTLE = (
    "💛 <b>Dikkat</b> — {date}\n\n"
    "Bugünün aktivite örüntüsü normalden farklı "
    "(skor: {composite_z:.1f}).\n\n"
    "{explanation}\n\n"
    "ℹ️ Muhtemelen endişelenecek bir durum yok, "
    "ancak göz kulak olmanızı öneririz."
)

TEMPLATE_ALERT_SERIOUS = (
    "🟠 <b>Önemli Uyarı</b> — {date}\n\n"
    "Belirgin bir aktivite anomalisi tespit edildi "
    "(skor: {composite_z:.1f}).\n\n"
    "{explanation}\n\n"
    "📞 Lütfen annenizi arayarak durumunu kontrol edin."
)

TEMPLATE_ALERT_EMERGENCY = (
    "🔴 <b>ACİL UYARI</b> — {date}\n\n"
    "Ciddi bir aktivite anomalisi tespit edildi "
    "(skor: {composite_z:.1f})!\n\n"
    "{explanation}\n\n"
    "🚨 HEMEN iletişime geçin veya komşu/yakınlardan "
    "kontrol etmesini isteyin!"
)

TEMPLATE_MORNING_SILENCE = (
    "☀️ <b>Sabah Kontrolü</b>\n\n"
    "Saat {check_time} itibarıyla bugün hiçbir "
    "sensörden hareket algılanmadı.\n\n"
    "📞 Lütfen annenizi arayarak durumunu kontrol edin."
)

TEMPLATE_LEARNING_PROGRESS = (
    "🧠 <b>Öğrenme Güncellemesi</b> — {date}\n\n"
    "Sistem {train_days}. gününde. "
    "Güven aralığı: ±{ci_pct:.0f}%\n\n"
    "{extra_message}"
)

TEMPLATE_LEARNING_COMPLETE = (
    "🎉 <b>Sistem Hazır!</b>\n\n"
    "14 günlük öğrenme dönemi tamamlandı. "
    "Güven düzeyi: %{confidence:.0f}\n\n"
    "Artık anormal aktivite durumlarında "
    "otomatik bildirim alacaksınız."
)

TEMPLATE_BATTERY_WARNING = (
    "🔋 <b>Düşük Pil Uyarısı</b>\n\n"
    "Sensör <b>{sensor_id}</b> pil seviyesi "
    "kritik düzeyde: <b>%{battery}</b>\n\n"
    "Lütfen en kısa sürede pil değiştirin."
)


# --- Render Fonksiyonlari ---

def render_daily_summary(
    date: str,
    composite_z: float,
    alert_level: int,
    train_days: int,
    ci_width: float,
    event_counts: dict[str, int],
) -> str:
    """Gunluk ozet mesaji olustur.

    Args:
        date: YYYY-MM-DD
        composite_z: Anomali skoru
        alert_level: 0-3
        train_days: Egitim gun sayisi
        ci_width: 0.0 - 1.0 arasinda, icerde yuzdeye cevrilir
        event_counts: {"presence": 42, "fridge": 8, ...}
    """
    if alert_level == 0:
        status = "✅ Her şey normal görünüyor."
    elif alert_level == 1:
        status = "💛 Hafif farklılık tespit edildi."
    elif alert_level == 2:
        status = "🟠 Belirgin anomali tespit edildi."
    else:
        status = "🔴 Ciddi anomali tespit edildi!"

    total_events = sum(event_counts.values())
    channel_names = {
        "presence": "Hareket",
        "fridge": "Buzdolabı",
        "bathroom": "Banyo",
        "door": "Kapı",
    }
    channel_lines = "\n".join(
        f"  • {channel_names.get(ch, ch)}: {cnt}"
        for ch, cnt in sorted(event_counts.items())
    )

    ci_pct = ci_width * 100.0

    return TEMPLATE_DAILY_SUMMARY.format(
        date=date,
        status=status,
        composite_z=composite_z,
        ci_pct=ci_pct,
        total_events=total_events,
        channel_lines=channel_lines,
        train_days=train_days,
    )


def render_alert(
    level: int,
    date: str,
    composite_z: float,
    explanation: str,
) -> str:
    """Kademeli alarm mesaji olustur.

    Args:
        level: 1=nazik, 2=ciddi, 3=acil. 0 ise bos string.
        date: YYYY-MM-DD
        composite_z: Anomali skoru
        explanation: generate_explanation() ciktisi
    """
    if level <= 0:
        return ""

    templates = {
        1: TEMPLATE_ALERT_GENTLE,
        2: TEMPLATE_ALERT_SERIOUS,
        3: TEMPLATE_ALERT_EMERGENCY,
    }
    template = templates.get(level, TEMPLATE_ALERT_EMERGENCY)

    return template.format(
        date=date,
        composite_z=composite_z,
        explanation=explanation,
    )


def render_morning_silence(check_time: str) -> str:
    """Sabah sessizlik alarm mesaji.

    Args:
        check_time: "HH:MM" formati
    """
    return TEMPLATE_MORNING_SILENCE.format(check_time=check_time)


def render_learning_progress(
    date: str,
    train_days: int,
    ci_width: float,
    extra_message: str = "",
) -> str:
    """Ogrenme sureci guncelleme mesaji.

    Args:
        date: YYYY-MM-DD
        train_days: Kacinci egitim gunu
        ci_width: 0.0 - 1.0 arasinda guven araligi
        extra_message: Ekstra not (bos olabilir)
    """
    ci_pct = ci_width * 100.0
    return TEMPLATE_LEARNING_PROGRESS.format(
        date=date,
        train_days=train_days,
        ci_pct=ci_pct,
        extra_message=extra_message,
    )


def render_learning_complete(confidence: float) -> str:
    """Ogrenme tamamlandi mesaji.

    Args:
        confidence: 0.0 - 100.0 arasinda guven yuzdesi
    """
    return TEMPLATE_LEARNING_COMPLETE.format(confidence=confidence)


def render_battery_warning(sensor_id: str, battery: int) -> str:
    """Dusuk pil uyari mesaji.

    Args:
        sensor_id: Sensor ID
        battery: Pil yuzdesi (0-100)
    """
    return TEMPLATE_BATTERY_WARNING.format(
        sensor_id=sensor_id,
        battery=battery,
    )
