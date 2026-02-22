"""KRITIK: NLL yon testleri - dusuk aktivite YUKSEK anomali skoru vermeli.

Bu testler v3'teki ters calisan NLL buginin tekrarlanmasini engeller.
Senaryo: Anne hic hareket etmemis gun vs normal gun.
"""

from src.learner.beta_model import BetaPosterior
from src.learner.metrics import calculate_daily_metrics

CHANNELS = ["presence", "fridge", "bathroom", "door"]


def _make_normal_day_model() -> dict[str, list[BetaPosterior]]:
    """14 gun egitilmis normal rutin modeli.

    Gunduz (slot 24-91): cogu slot active (Beta(10,4) -> mean~0.71)
    Gece (slot 0-23, 92-95): cogu slot inactive (Beta(2,12) -> mean~0.14)
    """
    model = {}
    for ch in CHANNELS:
        posteriors = []
        for s in range(96):
            if 24 <= s < 92:
                posteriors.append(BetaPosterior(10.0, 4.0))  # gunduz, genelde active
            else:
                posteriors.append(BetaPosterior(2.0, 12.0))  # gece, genelde inactive
        model[ch] = posteriors
    return model


def _normal_day_data() -> dict[str, list[int]]:
    """Normal bir gun: gunduz aktif, gece pasif."""
    data = {}
    for ch in CHANNELS:
        slots = []
        for s in range(96):
            if 24 <= s < 92:
                slots.append(1)
            else:
                slots.append(0)
        data[ch] = slots
    return data


def _zero_activity_day() -> dict[str, list[int]]:
    """Hic aktivite olmayan gun (anomali!)."""
    return {ch: [0] * 96 for ch in CHANNELS}


def test_zero_activity_higher_nll_than_normal():
    """SIFIR aktiviteli gun, normal gune gore DAHA YUKSEK nll_total vermeli.

    Bu test v3 bugini yakalar: dusuk aktivite yuksek NLL olmali.
    """
    model = _make_normal_day_model()
    normal_metrics = calculate_daily_metrics(_normal_day_data(), model)
    zero_metrics = calculate_daily_metrics(_zero_activity_day(), model)

    assert zero_metrics["nll_total"] > normal_metrics["nll_total"], (
        f"HATA: Sifir aktivite ({zero_metrics['nll_total']:.2f}) "
        f"normal gunden ({normal_metrics['nll_total']:.2f}) dusuk NLL verdi!"
    )


def test_fridge_never_opened_contributes_to_nll():
    """Buzdolabi hic acilmamis -> nll_fridge belirgin artis, nll_total farki >5."""
    model = _make_normal_day_model()

    normal_data = _normal_day_data()
    normal_metrics = calculate_daily_metrics(normal_data, model)

    # Anomali gunu: buzdolabi hic acilmamis, diger kanallar normal
    anomaly_data = _normal_day_data()
    anomaly_data["fridge"] = [0] * 96
    anomaly_metrics = calculate_daily_metrics(anomaly_data, model)

    # Buzdolabi NLL belirgin sekilde artmali
    assert anomaly_metrics["nll_fridge"] > normal_metrics["nll_fridge"], (
        "Buzdolabi hic acilmamis ama NLL artmadi!"
    )
    # nll_total'e anlamli katki (>5 birim fark)
    nll_diff = anomaly_metrics["nll_total"] - normal_metrics["nll_total"]
    assert nll_diff > 5.0, (
        f"Buzdolabi anomalisi toplam NLL'e yeterli katki yapmadi: fark={nll_diff:.2f}"
    )


def test_zero_activity_negative_count_z():
    """Sifir aktiviteli gun -> count_z NEGATIF olmali (beklenenden az olay)."""
    model = _make_normal_day_model()
    zero_metrics = calculate_daily_metrics(_zero_activity_day(), model)

    assert zero_metrics["count_z"] < -2.0, (
        f"Sifir aktivite count_z={zero_metrics['count_z']:.2f}, "
        f"-2'den kucuk olmali (belirgin anomali)!"
    )
