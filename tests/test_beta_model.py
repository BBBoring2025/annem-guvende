"""BetaPosterior hesaplama testleri - mean, variance, CI, NLL, update."""

import math

import pytest

from src.learner.beta_model import BetaPosterior


def test_mean_calculation():
    """Beta(3, 7) -> mean = 0.3."""
    bp = BetaPosterior(3.0, 7.0)
    assert bp.mean == pytest.approx(0.3)


def test_variance_calculation():
    """Beta(3, 7) -> variance = 3*7 / (10^2 * 11) = 21/1100."""
    bp = BetaPosterior(3.0, 7.0)
    expected_var = (3.0 * 7.0) / (10.0**2 * 11.0)
    assert bp.variance == pytest.approx(expected_var)


def test_std_calculation():
    """std = sqrt(variance)."""
    bp = BetaPosterior(3.0, 7.0)
    assert bp.std == pytest.approx(math.sqrt(bp.variance))


def test_credible_interval_bounds():
    """CI: lo >= 0, hi <= 1, lo < hi."""
    bp = BetaPosterior(1.0, 1.0)  # Uniform prior
    lo, hi = bp.credible_interval(0.90)
    assert lo >= 0.0
    assert hi <= 1.0
    assert lo < hi


def test_ci_width_decreases_with_data():
    """Daha fazla veri -> daha dar CI."""
    bp_start = BetaPosterior(1.0, 1.0)
    bp_trained = BetaPosterior(8.0, 8.0)  # 14 gun gozlem sonrasi
    assert bp_trained.ci_width < bp_start.ci_width


def test_nll_high_mean_observed_1():
    """mean yuksekken observed=1 -> dusuk NLL."""
    bp = BetaPosterior(9.0, 1.0)  # mean=0.9
    nll_val = bp.nll(1)
    expected = -math.log(0.9)  # ~0.105
    assert nll_val == pytest.approx(expected, rel=0.01)
    assert nll_val < 0.2


def test_nll_low_mean_observed_1():
    """mean dusukken observed=1 -> yuksek NLL."""
    bp = BetaPosterior(1.0, 9.0)  # mean=0.1
    nll_val = bp.nll(1)
    expected = -math.log(0.1)  # ~2.302
    assert nll_val == pytest.approx(expected, rel=0.01)
    assert nll_val > 2.0


def test_nll_non_negative():
    """NLL her zaman >= 0 olmali."""
    cases = [(1, 1, 0), (1, 1, 1), (5, 3, 0), (5, 3, 1), (1, 99, 0), (99, 1, 1)]
    for alpha, beta, obs in cases:
        bp = BetaPosterior(alpha, beta)
        assert bp.nll(obs) >= 0.0, f"NLL negatif: Beta({alpha},{beta}).nll({obs})"


def test_update_observed_1_increments_alpha():
    """observed=1 -> alpha + 1, beta ayni."""
    bp = BetaPosterior(3.0, 5.0)
    updated = bp.update(1)
    assert updated.alpha == 4.0
    assert updated.beta == 5.0


def test_update_observed_0_increments_beta():
    """observed=0 -> alpha ayni, beta + 1."""
    bp = BetaPosterior(3.0, 5.0)
    updated = bp.update(0)
    assert updated.alpha == 3.0
    assert updated.beta == 6.0


def test_update_immutable():
    """update() orijinal nesneyi degistirmemeli."""
    bp = BetaPosterior(3.0, 5.0)
    _ = bp.update(1)
    assert bp.alpha == 3.0
    assert bp.beta == 5.0
