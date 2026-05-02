"""Policy impact engine — translates policy clusters into asset-impact tags.

This is intentionally simple and explainable; the LLM lens pass adds nuance.
"""

from __future__ import annotations

from app.models.headline import HeadlineCluster

CHANNEL_TO_ASSETS: dict[str, list[str]] = {
    "monetary_policy": ["ZN", "ZF", "ZB", "ES", "DXY"],
    "treasury_issuance": ["ZN", "ZB", "UB"],
    "inflation": ["ZN", "ZF", "GC", "ES"],
    "labor_growth": ["ZN", "ES", "NQ", "DXY"],
    "central_bank_communication": ["ZN", "DXY", "6E", "6J"],
    "credit_stress": ["ES", "RTY", "ZN", "VX"],
    "banking_liquidity": ["RTY", "ZN", "VX"],
    "geopolitical_risk": ["CL", "GC", "ES", "VX", "DXY"],
    "energy_commodities": ["CL", "NG", "GC", "SI"],
    "china": ["HG", "CL", "ES", "6E"],
    "europe": ["6E", "ZN"],
    "japan": ["6J", "ZN"],
    "tariffs_sanctions": ["CL", "DXY", "ES", "HG"],
    "market_plumbing_volatility": ["VX", "ES"],
    "positioning": ["ES", "NQ", "ZN"],
}


def assets_for(cluster: HeadlineCluster) -> list[str]:
    return CHANNEL_TO_ASSETS.get(cluster.channel, [])


def impact_brief(cluster: HeadlineCluster) -> str:
    return f"{cluster.channel}: first-order on {', '.join(assets_for(cluster))}."
