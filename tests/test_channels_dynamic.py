"""Dinamik CHANNELS testleri."""

from src.learner.beta_model import BetaPosterior
from src.learner.metrics import DEFAULT_CHANNELS, calculate_daily_metrics


def _make_slot_data(channels):
    """Test icin minimal slot_data olustur."""
    return {ch: [0] * 96 for ch in channels}


def _make_model(channels):
    """Test icin minimal model olustur."""
    return {ch: [BetaPosterior(1.0, 1.0) for _ in range(96)] for ch in channels}


def test_default_channels_backward_compat():
    """channels=None ise DEFAULT_CHANNELS kullanilmali."""
    slot_data = _make_slot_data(DEFAULT_CHANNELS)
    model = _make_model(DEFAULT_CHANNELS)

    metrics = calculate_daily_metrics(slot_data, model)

    assert "nll_presence" in metrics
    assert "nll_fridge" in metrics
    assert "nll_total" in metrics


def test_custom_channels_only_those():
    """Sadece verilen kanallar metrikte olmali."""
    custom = ["presence", "fridge"]
    slot_data = _make_slot_data(custom)
    model = _make_model(custom)

    metrics = calculate_daily_metrics(slot_data, model, channels=custom)

    assert "nll_presence" in metrics
    assert "nll_fridge" in metrics
    assert "nll_bathroom" not in metrics
    assert "nll_door" not in metrics
    assert "nll_total" in metrics


def test_single_channel():
    """Tek kanal ile calisabilmeli."""
    custom = ["presence"]
    slot_data = _make_slot_data(custom)
    model = _make_model(custom)

    metrics = calculate_daily_metrics(slot_data, model, channels=custom)

    assert "nll_presence" in metrics
    assert "nll_total" in metrics
    assert metrics["nll_total"] == metrics["nll_presence"]


def test_extra_channel():
    """Standart olmayan kanal adi kullanilabilmeli."""
    custom = ["presence", "garage"]
    slot_data = _make_slot_data(custom)
    model = _make_model(custom)

    metrics = calculate_daily_metrics(slot_data, model, channels=custom)

    assert "nll_garage" in metrics
    assert "nll_presence" in metrics
