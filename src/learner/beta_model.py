"""Beta-Binomial model matematiksel cekirdegi.

BetaPosterior dataclass'i: mean, variance, CI, NLL, Bayesian update.
Harici bagimliligi yok (sadece stdlib math).
"""

import math
from dataclasses import dataclass


@dataclass
class BetaPosterior:
    """Beta dagilimi posterior parametreleri.

    alpha: prior + successes (aktif gozlem sayisi)
    beta:  prior + failures  (pasif gozlem sayisi)
    """

    alpha: float  # prior + successes
    beta: float   # prior + failures

    @property
    def mean(self) -> float:
        """Posterior ortalama: E[p] = alpha / (alpha + beta)."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        """Posterior varyans."""
        a, b = self.alpha, self.beta
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    @property
    def std(self) -> float:
        """Posterior standart sapma."""
        return math.sqrt(self.variance)

    def credible_interval(self, level: float = 0.90) -> tuple[float, float]:
        """Normal yaklasim ile credible interval.

        SciPy dogrulamasi: n>=7'de max %2 hata, n>=14'te ~%0.
        Uc degerlerde (p~0 veya p~1) hata artabilir.
        """
        z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}[level]
        lo = max(0.0, self.mean - z * self.std)
        hi = min(1.0, self.mean + z * self.std)
        return (lo, hi)

    @property
    def ci_width(self) -> float:
        """90% credible interval genisligi."""
        lo, hi = self.credible_interval()
        return hi - lo

    def nll(self, observed: int) -> float:
        """Negative log-likelihood: observed=0 veya 1.

        p [0.001, 0.999] araligina clamp edilir (log(0) onlemi).
        """
        p = max(0.001, min(0.999, self.mean))
        if observed == 1:
            return -math.log(p)
        else:
            return -math.log(1 - p)

    def update(self, observed: int) -> "BetaPosterior":
        """Yeni gozlemle posterior guncelle (immutable - yeni nesne dondurur)."""
        if observed == 1:
            return BetaPosterior(self.alpha + 1, self.beta)
        else:
            return BetaPosterior(self.alpha, self.beta + 1)
