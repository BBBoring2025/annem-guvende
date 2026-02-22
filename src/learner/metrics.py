"""Gunluk metrik hesaplamalari - NLL, count deviation, awake accuracy, CI.

Saf hesaplama modulu: DB erisimi yok, sadece veri + model alir, dict dondurur.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from src.learner.beta_model import BetaPosterior

if TYPE_CHECKING:
    from src.config import AppConfig

DEFAULT_CHANNELS = ["presence", "fridge", "bathroom", "door"]

# Geriye uyumluluk alias'i
CHANNELS = DEFAULT_CHANNELS


def get_channels_from_config(config: AppConfig) -> list[str]:
    """Config'deki sensor tanimlarindan kanal listesi cikar.

    Sensor yoksa DEFAULT_CHANNELS doner.
    """
    if config.sensors:
        return list({s.channel for s in config.sensors if s.channel})
    return list(DEFAULT_CHANNELS)


def calculate_daily_metrics(
    slot_data: dict[str, list[int]],
    model: dict[str, list[BetaPosterior]],
    awake_start: int = 24,
    awake_end: int = 92,
    channels: list[str] | None = None,
) -> dict:
    """Gunluk tum metrikleri hesapla ve dict olarak dondur.

    Args:
        slot_data: {channel: [96 active degeri (0/1)]}
        model: {channel: [96 BetaPosterior]}
        awake_start: Uyanik slot baslangici (default 24 = 06:00)
        awake_end: Uyanik slot bitisi (default 92 = 23:00)
        channels: Kanal listesi (None ise DEFAULT_CHANNELS)

    Returns:
        Dict: nll_*, expected_count, observed_count, count_z,
              aw_accuracy, aw_balanced_acc, aw_active_recall, avg_ci_width
    """
    ch_list = channels if channels is not None else list(DEFAULT_CHANNELS)
    metrics = {}

    # --- a) PER-SENSOR NLL (v3 duzeltmesi: her kanal ayri) ---
    nll_per_channel = {}
    for channel in ch_list:
        nll = sum(
            model[channel][s].nll(slot_data[channel][s])
            for s in range(96)
        )
        nll_per_channel[channel] = nll

    for channel in ch_list:
        metrics[f"nll_{channel}"] = nll_per_channel[channel]
    metrics["nll_total"] = sum(nll_per_channel.values())

    # --- b) EVENT COUNT DEVIATION ---
    expected = sum(
        model[ch][s].mean
        for ch in ch_list for s in range(96)
    )
    observed = sum(
        slot_data[ch][s]
        for ch in ch_list for s in range(96)
    )
    var_count = sum(
        model[ch][s].mean * (1 - model[ch][s].mean)
        for ch in ch_list for s in range(96)
    )
    count_z = (observed - expected) / math.sqrt(var_count) if var_count > 0 else 0.0

    metrics["expected_count"] = expected
    metrics["observed_count"] = observed
    metrics["count_z"] = count_z

    # --- c) AWAKE WINDOW ACCURACY ---
    aw_metrics = _calculate_awake_accuracy(slot_data, model, awake_start, awake_end, ch_list)
    metrics.update(aw_metrics)

    # --- d) CI WIDTH ---
    ci_widths = [
        model[ch][s].ci_width
        for ch in ch_list for s in range(96)
    ]
    metrics["avg_ci_width"] = sum(ci_widths) / len(ci_widths) if ci_widths else 1.0

    return metrics


def _calculate_awake_accuracy(
    slot_data: dict[str, list[int]],
    model: dict[str, list[BetaPosterior]],
    awake_start: int,
    awake_end: int,
    channels: list[str] | None = None,
) -> dict:
    """Awake window (06:00-23:00) uzerinde accuracy metrikleri.

    Tahmin: mean >= 0.5 -> predicted active, aksi halde inactive.
    """
    ch_list = channels if channels is not None else list(DEFAULT_CHANNELS)
    tp = 0  # true positive: predicted active, actually active
    tn = 0  # true negative: predicted inactive, actually inactive
    fp = 0  # false positive: predicted active, actually inactive
    fn = 0  # false negative: predicted inactive, actually active

    for ch in ch_list:
        for s in range(awake_start, awake_end):
            predicted = 1 if model[ch][s].mean >= 0.5 else 0
            actual = slot_data[ch][s]
            if predicted == 1 and actual == 1:
                tp += 1
            elif predicted == 0 and actual == 0:
                tn += 1
            elif predicted == 1 and actual == 0:
                fp += 1
            else:
                fn += 1

    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total > 0 else 0.0

    # Balanced accuracy = (sensitivity + specificity) / 2
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0  # active recall
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    balanced_acc = (sensitivity + specificity) / 2

    return {
        "aw_accuracy": accuracy,
        "aw_balanced_acc": balanced_acc,
        "aw_active_recall": sensitivity,
    }
