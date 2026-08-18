"""
Assembly time and shop-cost estimation for bead patterns.

Based on empirical data from makebead.com (2026) and Chinese bead-shop
reports.  The model accounts for:

* **Base placement speed** per experience tier (beginner_tier=10, normal=25,
  expert=40 beads/min).
* **Colour-switching overhead** — more colours reduce effective speed
  (≤8 colors ×1.0, 8–20 ×0.85, >20 ×0.7).  Tunable via *color_factor*.
* **Constant overhead** of 10 min for ironing and cooling.
* **Beginner flag** (CLI ``--beginner``) applies a 1.5× multiplier to the
  *normal*-tier estimate (not the beginner tier).

Public API
----------
    EstimateResult
        Dataclass: ``beads``, ``colors``, ``minutes``, ``hours``, ``cost``.

    estimate_time(beads, rate=25, colors=5, shop_rate=30, beginner=False)
        Compute estimated minutes, hours, and cost for all three tiers.

    estimate_cost(minutes, shop_rate=30)
        Convert assembly minutes to yuan (shop-rate × half-hour blocks).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class EstimateResult:
    """Immutable container for estimation results.

    Attributes
    ----------
    beads : int
        Total bead count (non-empty cells).
    colors : int
        Unique colour count.
    minutes : dict[str, float]
        Estimated minutes per tier (keys: ``beginner_tier``, ``normal``,
        ``expert``).
    hours : dict[str, float]
        Estimated hours per tier (= minutes / 60).
    cost : dict[str, float]
        Estimated shop cost in yuan per tier (keys: ``beginner``,
        ``normal``, ``expert``).
    """

    beads: int
    colors: int
    minutes: Dict[str, float]
    hours: Dict[str, float]
    cost: Dict[str, float]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate_time(
    beads: int,
    rate: float = 25,
    colors: int = 5,
    shop_rate: float = 30,
    beginner: bool = False,
) -> dict:
    """Estimate assembly time and shop cost for a bead pattern.

    Parameters
    ----------
    beads : int
        Total number of non-empty bead cells.
    rate : float
        Base placement speed for the *normal* tier (beads/min).  Default 25.
    colors : int
        Number of unique bead colours used.
    shop_rate : float
        Shop hourly rate in yuan.  Default 30.
    beginner : bool
        When ``True``, apply a 1.5× penalty to the *normal* tier minutes
        (corresponding to the CLI ``--beginner`` flag).

    Returns
    -------
    dict
        Keys: ``beads``, ``colors``, ``minutes``, ``hours``, ``cost``.
        See :class:`EstimateResult` for field descriptions.

    Raises
    ------
    ValueError
        If *rate* ≤ 0 or *shop_rate* ≤ 0.
    """
    if rate <= 0:
        raise ValueError("rate must be greater than 0")
    if shop_rate <= 0:
        raise ValueError("shop_rate must be greater than 0")

    # --- colour difficulty factor (tunable, experience-based estimate) ---
    if colors <= 8:
        color_factor = 1.0
    elif colors <= 20:
        color_factor = 0.85
    else:
        color_factor = 0.7

    # --- base tier rates (beads / min) ---
    tier_rates: Dict[str, float] = {
        "beginner_tier": 10.0,
        "normal": float(rate),
        "expert": 40.0,
    }

    # --- minutes per tier ---
    minutes: Dict[str, float] = {}
    for tier, r in tier_rates.items():
        rate_eff = r * color_factor
        minutes[tier] = beads / max(rate_eff, 0.001) + 10.0

    # --- beginner flag: multiply *normal* tier by 1.5× ---
    if beginner:
        minutes["normal"] *= 1.5

    # --- hours ---
    hours: Dict[str, float] = {
        tier: m / 60.0 for tier, m in minutes.items()
    }

    # --- cost per tier (yuan) ---
    cost: Dict[str, float] = {}
    # Cost keys are "beginner", "normal", "expert" (not "beginner_tier")
    cost_map = {"beginner_tier": "beginner", "normal": "normal", "expert": "expert"}
    for tier_key, out_key in cost_map.items():
        cost[out_key] = estimate_cost(minutes[tier_key], shop_rate)

    return {
        "beads": beads,
        "colors": colors,
        "minutes": minutes,
        "hours": hours,
        "cost": cost,
    }


def estimate_cost(minutes: float, shop_rate: float = 30) -> float:
    """Convert assembly minutes to shop cost (yuan).

    Cost is charged in 0.5-hour blocks, rounded up:

        cost = ceil(minutes / 30) × 0.5 × shop_rate

    Parameters
    ----------
    minutes : float
        Estimated assembly minutes.
    shop_rate : float
        Shop hourly rate in yuan.  Default 30.

    Returns
    -------
    float
        Estimated cost in yuan.

    Raises
    ------
    ValueError
        If *shop_rate* ≤ 0.
    """
    if shop_rate <= 0:
        raise ValueError("shop_rate must be greater than 0")
    half_hours = math.ceil(minutes / 30.0)
    return half_hours * 0.5 * shop_rate
