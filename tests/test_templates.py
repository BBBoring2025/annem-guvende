"""Mesaj sablonu render testleri."""

from src.alerter.message_templates import (
    render_alert,
    render_daily_summary,
    render_learning_complete,
    render_learning_progress,
    render_morning_silence,
)


def test_render_daily_summary_normal():
    """Normal gun ozeti: tarih, event sayilari, durum mesaji iceriyor."""
    result = render_daily_summary(
        date="2025-03-01",
        composite_z=0.8,
        alert_level=0,
        train_days=20,
        ci_width=0.15,
        event_counts={"presence": 50, "fridge": 8, "bathroom": 12, "door": 4},
    )

    assert "2025-03-01" in result
    assert "normal" in result.lower()
    assert "74" in result  # toplam: 50+8+12+4
    assert "Hareket" in result
    assert "Buzdolabı" in result
    assert "20. gün" in result
    assert "15%" in result  # ci_width 0.15 -> %15


def test_render_daily_summary_alert_levels():
    """Farkli alert level'lar farkli durum mesajlari uretir."""
    base_args = dict(
        date="2025-03-01",
        composite_z=2.5,
        train_days=15,
        ci_width=0.1,
        event_counts={"presence": 10},
    )

    r0 = render_daily_summary(alert_level=0, **base_args)
    r1 = render_daily_summary(alert_level=1, **base_args)
    r2 = render_daily_summary(alert_level=2, **base_args)
    r3 = render_daily_summary(alert_level=3, **base_args)

    assert "normal" in r0.lower()
    assert "Hafif" in r1
    assert "Belirgin" in r2
    assert "Ciddi" in r3


def test_render_alert_level_1():
    """Level 1: 'Dikkat' anahtar kelimesi, skor ve aciklama iceriyor."""
    result = render_alert(
        level=1,
        date="2025-03-01",
        composite_z=2.3,
        explanation="Buzdolabı aktivitesi beklenenden düşük.",
    )

    assert "Dikkat" in result
    assert "2.3" in result
    assert "Buzdolabı" in result


def test_render_alert_level_2():
    """Level 2: 'Uyarı' ve 'arayarak' iceriyor."""
    result = render_alert(
        level=2,
        date="2025-03-01",
        composite_z=3.2,
        explanation="Toplam aktivite çok düşük.",
    )

    assert "Uyarı" in result
    assert "arayarak" in result
    assert "3.2" in result


def test_render_alert_level_3():
    """Level 3: 'ACİL' ve 'HEMEN' iceriyor."""
    result = render_alert(
        level=3,
        date="2025-03-01",
        composite_z=4.5,
        explanation="Hiçbir aktivite algılanmadı.",
    )

    assert "ACİL" in result
    assert "HEMEN" in result
    assert "4.5" in result


def test_render_alert_level_0_empty():
    """Level 0: bos string dondurur."""
    result = render_alert(
        level=0,
        date="2025-03-01",
        composite_z=0.5,
        explanation="",
    )

    assert result == ""


def test_render_morning_silence():
    """Sabah sessizlik: check_time iceriyor."""
    result = render_morning_silence(check_time="11:30")

    assert "11:30" in result
    assert "Sabah" in result
    assert "sensör" in result.lower()


def test_render_learning_progress():
    """Ogrenme sureci: train_days, ci_width yuzde iceriyor."""
    result = render_learning_progress(
        date="2025-03-07",
        train_days=7,
        ci_width=0.25,
        extra_message="Yarısına geldik!",
    )

    assert "7. gün" in result
    assert "25%" in result
    assert "Yarısına geldik!" in result


def test_render_learning_complete():
    """Ogrenme tamamlandi: 'Sistem Hazır' ve confidence iceriyor."""
    result = render_learning_complete(confidence=92.0)

    assert "Sistem Hazır" in result
    assert "92" in result
    assert "tamamlandı" in result
