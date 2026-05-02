"""Different regimes produce different top personas."""

from app.analysis.persona_weights import top_personas
from app.models.macro_signal import Regime


def _names(regime):
    return {n for n, _, _ in top_personas(regime, n=4)}


def test_credit_stress_promotes_chanos_burry_gundlach():
    names = _names(Regime.CREDIT_STRESS)
    assert "Gundlach" in names
    assert "Burry" in names or "Chanos" in names


def test_policy_mistake_promotes_soros():
    assert "Soros" in _names(Regime.POLICY_MISTAKE)


def test_liquidity_withdrawal_promotes_gross_gundlach_druckenmiller():
    n = _names(Regime.LIQUIDITY_WITHDRAWAL)
    assert {"Gross", "Gundlach", "Druckenmiller"}.issubset(n)


def test_geopolitical_shock_promotes_ptj_or_bacon():
    n = _names(Regime.GEOPOLITICAL_SHOCK)
    assert "PTJ" in n or "Bacon" in n


def test_no_signal_no_special_top():
    # baseline-everywhere — top set varies, but all should be in PERSONAS dict
    n = _names(Regime.NO_SIGNAL)
    assert len(n) == 4
