"""Black-76 sanity checks against put-call parity and a known reference value."""

import math

import pytest

from app.analysis.option_pricing import black76, implied_vol
from app.models.option_contract import OptionType


def test_put_call_parity():
    F, K, sigma, T, r = 100.0, 100.0, 0.20, 0.50, 0.05
    c = black76(F, K, sigma, T, r, OptionType.CALL).price
    p = black76(F, K, sigma, T, r, OptionType.PUT).price
    # parity for futures: C - P = e^{-rT} (F - K)
    lhs = c - p
    rhs = math.exp(-r * T) * (F - K)
    assert lhs == pytest.approx(rhs, abs=1e-8)


def test_atm_call_known_value():
    # ATM, 1y, sigma=0.30, r=0.0 -> closed form: F * (2 N(0.15) - 1)
    F, K, sigma, T, r = 100.0, 100.0, 0.30, 1.0, 0.0
    res = black76(F, K, sigma, T, r, OptionType.CALL)
    from scipy.stats import norm
    expected = F * (2 * norm.cdf(0.15) - 1.0)
    assert res.price == pytest.approx(expected, abs=1e-6)


def test_iv_solver_roundtrip():
    F, K, T, r = 110.0, 109.5, 0.10, 0.05
    sigma_true = 0.075
    px = black76(F, K, sigma_true, T, r, OptionType.PUT).price
    iv = implied_vol(F, K, px, T, r, OptionType.PUT)
    assert iv == pytest.approx(sigma_true, abs=5e-4)


def test_no_zero_vol_allowed():
    with pytest.raises(ValueError):
        black76(100.0, 100.0, 0.0, 1.0, 0.05, OptionType.CALL)


def test_no_arb_violation_iv_solver():
    # market price below intrinsic should fail
    F, K, T, r = 100.0, 90.0, 0.10, 0.05
    intrinsic = math.exp(-r * T) * (F - K)
    with pytest.raises(ValueError):
        implied_vol(F, K, intrinsic - 0.5, T, r, OptionType.CALL)


def test_greeks_signs():
    res_call = black76(100, 100, 0.2, 0.5, 0.0, OptionType.CALL)
    res_put = black76(100, 100, 0.2, 0.5, 0.0, OptionType.PUT)
    assert res_call.delta > 0
    assert res_put.delta < 0
    assert res_call.gamma > 0 and res_put.gamma > 0
    assert res_call.vega > 0 and res_put.vega > 0
