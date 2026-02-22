"""AlertManager testleri - daily summary CI width hesabi."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.alerter.alert_manager import AlertManager
from src.alerter.telegram_bot import TelegramNotifier
from src.config import AppConfig
from src.database import get_db, init_db
from src.learner.beta_model import BetaPosterior


def _make_manager():
    """Test icin minimal AlertManager olustur."""
    config = AppConfig(
        alerts={"z_threshold_gentle": 2.0, "z_threshold_serious": 3.0, "z_threshold_emergency": 4.0, "min_train_days": 7},
    )
    mock_notifier = MagicMock(spec=TelegramNotifier)
    mock_notifier.enabled = False
    return AlertManager(config, mock_notifier), mock_notifier


def test_daily_summary_uses_model_ci_width(tmp_path):
    """model_state varsa CI width gercek posterior'dan hesaplanmali."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    # Bilinen alpha/beta degerleri ile model_state ekle
    known_posteriors = [
        (0, "presence", 10.0, 5.0),   # ci_width = BetaPosterior(10, 5).ci_width
        (0, "fridge", 3.0, 12.0),
        (1, "presence", 8.0, 8.0),
        (1, "fridge", 6.0, 6.0),
    ]

    with get_db(db_path) as conn:
        for slot, ch, alpha, beta in known_posteriors:
            conn.execute(
                "INSERT INTO model_state (slot, channel, alpha, beta) VALUES (?, ?, ?, ?)",
                (slot, ch, alpha, beta),
            )
        # daily_scores ekle (bugun icin)
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            """INSERT INTO daily_scores (date, train_days, nll_presence, nll_fridge,
               nll_bathroom, nll_door, nll_total, expected_count, observed_count,
               count_z, composite_z, alert_level, is_learning)
               VALUES (?, 10, 0.5, 0.5, 0.5, 0.5, 2.0, 50, 48, -0.3, 0.5, 0, 0)""",
            (today,),
        )
        conn.commit()

    # Beklenen CI width
    expected_ci = sum(
        BetaPosterior(a, b).ci_width for _, _, a, b in known_posteriors
    ) / len(known_posteriors)

    manager, mock_notifier = _make_manager()
    mock_notifier.enabled = True

    # render_daily_summary'e gecilen ci_width'i yakala
    with patch("src.alerter.alert_manager.render_daily_summary") as mock_render:
        mock_render.return_value = "test"
        manager.handle_daily_summary(db_path)

        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args
        actual_ci = call_kwargs.kwargs.get("ci_width") or call_kwargs[1].get("ci_width")
        # Keyword argument olarak gecilmis olmali
        if actual_ci is None:
            # Positional argument olarak gecilmis olabilir
            # render_daily_summary(date, composite_z, alert_level, train_days, ci_width, event_counts)
            actual_ci = call_kwargs[1]["ci_width"] if "ci_width" in call_kwargs[1] else call_kwargs[0][4]

    assert abs(actual_ci - expected_ci) < 1e-6, (
        f"CI width model_state'ten hesaplanmali: expected={expected_ci:.6f}, got={actual_ci:.6f}"
    )


def test_daily_summary_fallback_without_model_state(tmp_path):
    """model_state bossa fallback formul kullanilmali."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    today = datetime.now().strftime("%Y-%m-%d")
    with get_db(db_path) as conn:
        conn.execute(
            """INSERT INTO daily_scores (date, train_days, nll_presence, nll_fridge,
               nll_bathroom, nll_door, nll_total, expected_count, observed_count,
               count_z, composite_z, alert_level, is_learning)
               VALUES (?, 10, 0.5, 0.5, 0.5, 0.5, 2.0, 50, 48, -0.3, 0.5, 0, 0)""",
            (today,),
        )
        conn.commit()

    # model_state bos → fallback: max(0.05, 1.0/10) = 0.1
    expected_ci = max(0.05, 1.0 / 10)

    manager, mock_notifier = _make_manager()
    mock_notifier.enabled = True

    with patch("src.alerter.alert_manager.render_daily_summary") as mock_render:
        mock_render.return_value = "test"
        manager.handle_daily_summary(db_path)

        call_kwargs = mock_render.call_args
        actual_ci = call_kwargs.kwargs.get("ci_width") or call_kwargs[1].get("ci_width")
        if actual_ci is None:
            actual_ci = call_kwargs[0][4]

    assert abs(actual_ci - expected_ci) < 1e-6
