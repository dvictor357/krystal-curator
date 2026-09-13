"""What to type into Krystal's Automation form for a position.

No signing, no API writes: this only derives sensible values (from pool volatility, fee
tier, position size and the active risk profile) and labels them exactly as Krystal's
UI does, so you can copy them over in a minute.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .positions import Position
from .profiles import RiskProfile

# target hold before the next rebalance, per profile → range width = σ·√days (68 %)
HOLD_DAYS = {"conservative": 14.0, "balanced": 7.0, "aggressive": 3.0, "degen": 1.0}
# emergency-exit loss threshold (price below the range floor by this much), per profile
EXIT_LOSS_PCT = {"conservative": 8.0, "balanced": 15.0, "aggressive": 25.0, "degen": None}


@dataclass(slots=True, frozen=True)
class Field:
    section: str  # Rebalance / Auto Compound / Auto Harvest / Auto Exit
    label: str  # exactly as in Krystal's form
    value: str
    why: str


@dataclass(slots=True, frozen=True)
class Setup:
    fields: list[Field]
    range_pct: float
    hold_days: float
    sigma: float | None

    def by_section(self) -> dict[str, list[Field]]:
        out: dict[str, list[Field]] = {}
        for f in self.fields:
            out.setdefault(f.section, []).append(f)
        return out


def _round_half(x: float) -> float:
    return math.ceil(x * 2) / 2


def recommend(p: Position, sigma_daily_pct: float | None, prof: RiskProfile) -> Setup:
    sig = sigma_daily_pct if sigma_daily_pct and sigma_daily_pct > 0 else 5.0
    hold = HOLD_DAYS.get(prof.key, 7.0)
    width = max(1.0, _round_half(sig * math.sqrt(hold)))  # ±% around spot
    buffer_h = min(6.0, max(0.5, round(sig / 4 * 2) / 2))
    swap_slip = min(3.0, max(0.5, round(sig / 10 * 2) / 2))
    pool_slip = 1.0 if sig > 30 else 0.5
    gas_ceiling = max(1.0, min(5.0, p.value * 0.005))
    min_fee = max(10.0, round(p.value * 0.005))
    cur = p.current_price or 0.0
    lo = cur * (1 - width / 100) if cur else 0.0
    hi = cur * (1 + width / 100) if cur else 0.0
    fields: list[Field] = [
        Field(
            "Rebalance",
            "Rebalancing Trigger",
            "Below Future Spot Price: current Min Price   Above Future Spot Price: current Max Price",
            "rebalance the moment price leaves the range you hold now",
        ),
        Field(
            "Rebalance",
            "Time Buffer",
            f"{buffer_h:g} h",
            f"price must stay outside for this long — σ {sig:.1f}%/d, avoids whipsaw rebalances",
        ),
        Field(
            "Rebalance",
            "New Range",
            f"Below Future Spot Price −{width:g}%   Above Future Spot Price +{width:g}%",
            f"σ·√{hold:g}d = ±{width:g}% holds ~68% of {hold:g}-day outcomes ({prof.key})",
        ),
        Field(
            "Rebalance",
            "Swap Slippage",
            f"{swap_slip:g}%",
            "rebalance swaps half the position; ~σ/10 so it does not revert on volatile pairs",
        ),
        Field("Rebalance", "Pool Slippage", f"{pool_slip:g}%", "liquidity add/remove tolerance"),
        Field(
            "Rebalance",
            "Gas Fee Ceiling",
            f"{gas_ceiling:.2f} $",
            "Robinhood gas is cents; Krystal requires ≥ 2× the estimate — keep small",
        ),
        Field("Rebalance", "Recurring", "on", "re-arm after every rebalance"),
        Field(
            "Auto Compound",
            "Compound Trigger / Minimum compound amount",
            f"Trigger by Fee, {min_fee:,.0f} $",
            "fees back into the position once they cover gas many times over (~0.5% of value)",
        ),
        Field(
            "Auto Harvest",
            "Harvest Trigger / Minimum harvest amount",
            f"Trigger by Fee, {min_fee:,.0f} $  (only if you want fees paid out instead of compounded)",
            "pick Compound OR Harvest, not both",
        ),
    ]
    loss = EXIT_LOSS_PCT.get(prof.key)
    if loss is not None and p.min_price > 0:
        exit_price = p.min_price * (1 - loss / 100)
        fields.append(
            Field(
                "Auto Exit",
                "Emergency Exit — Trigger at",
                f"price below {exit_price:,.4g}  (range floor {p.min_price:,.4g} − {loss:g}%)",
                f"{prof.key}: cap the loss on a one-way move; exit to {p.token1 if p.token0.upper() != 'USDG' else p.token0}",
            )
        )
        fields.append(Field("Auto Exit", "Time Buffer", f"{buffer_h:g} h", "same whipsaw guard"))
    else:
        fields.append(Field("Auto Exit", "Emergency Exit", "off", f"{prof.key} profile: no stop"))
    fields.append(Field("General", "Setup expired time", "30 days", "review monthly"))
    if cur:
        fields.append(
            Field(
                "General",
                "resulting range now",
                f"{lo:,.4g} – {hi:,.4g}",
                "what the New Range % means at today's price",
            )
        )
    return Setup(fields, width, hold, sigma_daily_pct)
