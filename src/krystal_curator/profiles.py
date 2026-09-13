"""Risk profiles: hard filters + scoring weights + normalisation caps."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RiskProfile:
    key: str
    name: str
    blurb: str

    # hard filters
    min_tvl: float
    min_vol24: float
    max_volatility: float  # priceVolatility, percent
    max_drawdown: float  # abs(drawdown24h), percent
    max_fee_tier: float  # percent; very high tiers = illiquid memecoins
    allow_new: bool  # pools with < 1 day of history
    require_lp_auto: bool  # Krystal can auto-manage (rebalance) the position

    # normalisation caps: metric / cap → 1.0 = full marks
    cap_yield: float  # daily fee yield (fraction)
    cap_turnover: float  # vol24 / tvl

    # weights, summed to 100
    w_yield: float
    w_turnover: float
    w_consistency: float
    w_liveness: float
    w_depth: float
    w_risk: float

    @property
    def weights(self) -> dict[str, float]:
        return {
            "yield": self.w_yield,
            "turnover": self.w_turnover,
            "consistency": self.w_consistency,
            "liveness": self.w_liveness,
            "depth": self.w_depth,
            "risk": self.w_risk,
        }


PROFILES: dict[str, RiskProfile] = {
    p.key: p
    for p in (
        RiskProfile(
            key="conservative",
            name="CONSERVATIVE",
            blurb="Deep blue-chip pools, steady fees, low price risk. WETH/USDG class.",
            min_tvl=1_000_000,
            min_vol24=1_000_000,
            max_volatility=15,
            max_drawdown=15,
            max_fee_tier=1.0,
            allow_new=False,
            require_lp_auto=True,
            cap_yield=0.01,
            cap_turnover=3,
            w_yield=20,
            w_turnover=15,
            w_consistency=25,
            w_liveness=5,
            w_depth=20,
            w_risk=15,
        ),
        RiskProfile(
            key="balanced",
            name="BALANCED",
            blurb="Established mid-caps with real turnover. Some vol, must have 7d track record.",
            min_tvl=250_000,
            min_vol24=250_000,
            max_volatility=40,
            max_drawdown=35,
            max_fee_tier=3.0,
            allow_new=False,
            require_lp_auto=True,
            cap_yield=0.05,
            cap_turnover=8,
            w_yield=30,
            w_turnover=20,
            w_consistency=20,
            w_liveness=5,
            w_depth=10,
            w_risk=15,
        ),
        RiskProfile(
            key="aggressive",
            name="AGGRESSIVE",
            blurb="High-fee-tier movers. Big daily yield, accept drawdowns, active rebalancing.",
            min_tvl=50_000,
            min_vol24=100_000,
            max_volatility=70,
            max_drawdown=60,
            max_fee_tier=6.0,
            allow_new=True,
            require_lp_auto=True,
            cap_yield=0.15,
            cap_turnover=15,
            w_yield=40,
            w_turnover=20,
            w_consistency=15,
            w_liveness=10,
            w_depth=5,
            w_risk=10,
        ),
        RiskProfile(
            key="degen",
            name="DEGEN",
            blurb="Anything with volume. Pure fee-yield chase, no safety rails.",
            min_tvl=10_000,
            min_vol24=25_000,
            max_volatility=1e9,
            max_drawdown=1e9,
            max_fee_tier=1e9,
            allow_new=True,
            require_lp_auto=False,
            cap_yield=0.50,
            cap_turnover=30,
            w_yield=50,
            w_turnover=25,
            w_consistency=5,
            w_liveness=15,
            w_depth=0,
            w_risk=5,
        ),
    )
}

PROFILE_ORDER = list(PROFILES)
