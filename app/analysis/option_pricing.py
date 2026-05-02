"""Black-76 pricing for European options on futures.

Reference: Black (1976). Pricing of commodity contracts.

Forward price F. Strike K. Volatility sigma (annualized, decimal). Time to
expiry T (years). Risk-free rate r (continuously-compounded, decimal).

  d1 = (ln(F/K) + 0.5 sigma^2 T) / (sigma sqrt(T))
  d2 = d1 - sigma sqrt(T)

  Call = e^{-rT} * (F * N(d1) - K * N(d2))
  Put  = e^{-rT} * (K * N(-d2) - F * N(-d1))

Greeks here are returned in Black-76 conventions:
  delta_call = e^{-rT} N(d1)
  delta_put  = -e^{-rT} N(-d1)
  gamma      = e^{-rT} phi(d1) / (F sigma sqrt(T))
  vega       = F e^{-rT} phi(d1) sqrt(T)              (per 1.00 vol; divide by 100 for per-pct)
  theta_call = -F e^{-rT} phi(d1) sigma / (2 sqrt(T))
                + r F e^{-rT} N(d1) - r K e^{-rT} N(d2)
  theta_put  = -F e^{-rT} phi(d1) sigma / (2 sqrt(T))
                - r F e^{-rT} N(-d1) + r K e^{-rT} N(-d2)
  (theta returned per-year here; divide by 365 for per-day)

VX (VIX futures options) is intentionally NOT routed through Black-76 in this
repo. The trade selector flags VX separately and refuses to price it directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

from app.models.option_contract import OptionType


@dataclass
class Black76Result:
    price: float
    delta: float
    gamma: float
    vega: float           # per 1.00 of vol (i.e. multiply by 0.01 for per-1%-pt)
    theta: float          # per year — divide by 365 for per-day
    d1: float
    d2: float


def _safe_sqrt_t(T: float) -> float:
    return math.sqrt(max(T, 1e-12))


def black76(F: float, K: float, sigma: float, T: float, r: float, option_type: OptionType) -> Black76Result:
    if F <= 0 or K <= 0:
        raise ValueError("F and K must be positive")
    if sigma <= 0:
        raise ValueError("sigma must be positive (no IV fallback permitted)")

    sqrtT = _safe_sqrt_t(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    disc = math.exp(-r * T)
    n_d1 = norm.cdf(d1)
    n_d2 = norm.cdf(d2)
    pdf_d1 = norm.pdf(d1)

    if option_type == OptionType.CALL:
        price = disc * (F * n_d1 - K * n_d2)
        delta = disc * n_d1
        theta = (
            -F * disc * pdf_d1 * sigma / (2.0 * sqrtT)
            + r * F * disc * n_d1
            - r * K * disc * n_d2
        )
    else:
        price = disc * (K * norm.cdf(-d2) - F * norm.cdf(-d1))
        delta = -disc * norm.cdf(-d1)
        theta = (
            -F * disc * pdf_d1 * sigma / (2.0 * sqrtT)
            - r * F * disc * norm.cdf(-d1)
            + r * K * disc * norm.cdf(-d2)
        )

    gamma = disc * pdf_d1 / (F * sigma * sqrtT)
    vega = F * disc * pdf_d1 * sqrtT
    return Black76Result(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta, d1=d1, d2=d2)


def implied_vol(F: float, K: float, market_price: float, T: float, r: float,
                option_type: OptionType, *, tol: float = 1e-6, max_iter: int = 100) -> float:
    """Brent-bracketed Newton solver for Black-76 IV.

    Returns sigma. If market_price violates no-arb bounds, raises ValueError —
    the caller should treat that as missing data and emit NO TRADE.
    """
    disc = math.exp(-r * T)
    if option_type == OptionType.CALL:
        intrinsic = disc * max(F - K, 0.0)
        upper = disc * F
    else:
        intrinsic = disc * max(K - F, 0.0)
        upper = disc * K
    if market_price < intrinsic - 1e-8 or market_price > upper + 1e-8:
        raise ValueError(f"market price {market_price} outside no-arb [{intrinsic:.6f}, {upper:.6f}]")

    lo, hi = 1e-5, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        px = black76(F, K, mid, T, r, option_type).price
        if abs(px - market_price) < tol:
            return mid
        if px > market_price:
            hi = mid
        else:
            lo = mid
    return mid
