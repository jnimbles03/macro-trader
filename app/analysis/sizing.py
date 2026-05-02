"""Position sizing.

  spread_contracts = floor((account * risk_per_spread_pct/100) / max_loss_per_spread)
  yolo_contracts   = floor((account * risk_per_yolo_pct/100)   / premium_per_yolo)

If DEFAULT_ACCOUNT_SIZE is unset, return 0 contracts and a sizing note in
"$X risk per Y contracts" form.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.config import get_settings


@dataclass
class SizingResult:
    contracts: int
    risk_dollars: float | None
    note: str


def size_spread(max_loss_dollars: float) -> SizingResult:
    s = get_settings()
    if max_loss_dollars <= 0:
        return SizingResult(contracts=0, risk_dollars=None, note="max_loss must be > 0")
    if s.default_account_size is None:
        return SizingResult(
            contracts=0,
            risk_dollars=None,
            note=f"${max_loss_dollars:.2f} max loss per spread; account size unset — "
                 f"size manually using {s.default_risk_per_spread_pct:.2f}% rule",
        )
    budget = s.default_account_size * (s.default_risk_per_spread_pct / 100.0)
    contracts = max(0, math.floor(budget / max_loss_dollars))
    return SizingResult(
        contracts=contracts,
        risk_dollars=contracts * max_loss_dollars,
        note=f"{s.default_risk_per_spread_pct:.2f}% of ${s.default_account_size:.0f} = ${budget:.2f} budget",
    )


def size_yolo(premium_per_yolo_dollars: float) -> SizingResult:
    s = get_settings()
    if premium_per_yolo_dollars <= 0:
        return SizingResult(contracts=0, risk_dollars=None, note="premium must be > 0")
    if s.default_account_size is None:
        return SizingResult(
            contracts=0,
            risk_dollars=None,
            note=f"${premium_per_yolo_dollars:.2f} max loss per YOLO contract; "
                 f"account size unset — size manually using {s.default_risk_per_yolo_pct:.2f}% rule",
        )
    budget = s.default_account_size * (s.default_risk_per_yolo_pct / 100.0)
    contracts = max(0, math.floor(budget / premium_per_yolo_dollars))
    return SizingResult(
        contracts=contracts,
        risk_dollars=contracts * premium_per_yolo_dollars,
        note=f"{s.default_risk_per_yolo_pct:.2f}% of ${s.default_account_size:.0f} = ${budget:.2f} budget",
    )
