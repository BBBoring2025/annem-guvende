"""Metrik hesaplama testleri - bilinen veriyle dogrulama."""

import math

import pytest

from src.learner.beta_model import BetaPosterior
from src.learner.metrics import calculate_daily_metrics

CHANNELS = ["presence", "fridge", "bathroom", "door"]


def _make_uniform_model() -> dict[str, list[BetaPosterior]]:
    """Tum slotlar icin Beta(1,1) model (uniform prior)."""
    return {ch: [BetaPosterior(1.0, 1.0) for _ in range(96)] for ch in CHANNELS}


def _make_trained_model(active_mean: float = 0.7) -> dict[str, list[BetaPosterior]]:
    """Egitilmis model: belirtilen ortalama ile."""
    alpha = active_mean * 10
    beta = (1 - active_mean) * 10
    return {ch: [BetaPosterior(alpha, beta) for _ in range(96)] for ch in CHANNELS}


def _make_slot_data(active_value: int) -> dict[str, list[int]]:
    """Tum slotlar ayni deger."""
    return {ch: [active_value] * 96 for ch in CHANNELS}


def test_nll_per_channel_correct():
    """Bilinen model ve veri icin per-channel NLL dogru hesaplanmali."""
    model = {ch: [BetaPosterior(9.0, 1.0)] * 96 for ch in CHANNELS}
    slot_data = _make_slot_data(1)
    metrics = calculate_daily_metrics(slot_data, model)

    # Her kanal: 96 * (-log(0.9)) = 96 * 0.10536 ~= 10.114
    expected_per_ch = 96 * (-math.log(0.9))
    assert metrics["nll_presence"] == pytest.approx(expected_per_ch, rel=0.01)
    assert metrics["nll_total"] == pytest.approx(4 * expected_per_ch, rel=0.01)


def test_count_z_all_active():
    """Tum slotlar active, model mean=0.5 -> pozitif count_z."""
    model = _make_uniform_model()
    slot_data = _make_slot_data(1)
    metrics = calculate_daily_metrics(slot_data, model)

    assert metrics["count_z"] > 0
    assert metrics["observed_count"] == 384
    assert metrics["expected_count"] == pytest.approx(192.0)


def test_count_z_zero_active():
    """Hic aktivite yok, model mean=0.5 -> negatif count_z."""
    model = _make_uniform_model()
    slot_data = _make_slot_data(0)
    metrics = calculate_daily_metrics(slot_data, model)

    assert metrics["count_z"] < 0
    assert metrics["observed_count"] == 0


def test_awake_accuracy_perfect_model():
    """Model her slot icin dogru tahmin -> %100 accuracy."""
    model = _make_trained_model(0.9)  # predict: active (mean>0.5)
    slot_data = _make_slot_data(1)     # gercek: active
    metrics = calculate_daily_metrics(slot_data, model)

    assert metrics["aw_accuracy"] == 1.0
    assert metrics["aw_active_recall"] == 1.0


def test_awake_accuracy_zero_when_all_wrong():
    """Model hep active tahmin ediyor ama hic aktivite yok."""
    model = _make_trained_model(0.9)  # predict: active
    slot_data = _make_slot_data(0)     # gercek: inactive
    metrics = calculate_daily_metrics(slot_data, model)

    assert metrics["aw_active_recall"] == 0.0
    assert metrics["aw_accuracy"] == 0.0


def test_ci_width_narrow_after_training():
    """Egitilmis model uniform'a gore daha dar CI vermeli."""
    uniform_model = _make_uniform_model()
    trained_model = _make_trained_model(0.7)

    slot_data = _make_slot_data(1)
    metrics_uniform = calculate_daily_metrics(slot_data, uniform_model)
    metrics_trained = calculate_daily_metrics(slot_data, trained_model)

    assert metrics_trained["avg_ci_width"] < metrics_uniform["avg_ci_width"]
