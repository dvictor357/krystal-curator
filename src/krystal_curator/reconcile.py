"""Cross-check one pool feed against the other.

Krystal's LP explorer and robinhoodpools measure the same pools by different means
(vendor aggregation vs chain events, both USDG-quoted). Where they disagree, one of
them is stale, mispriced, or counting something the other does not (v4 manager balance
vs active liquidity, wash volume, ...). The delta is not a verdict, it is a prompt to
look. Pools are matched on pool id: 20-byte address for v2/v3, 32-byte id for v4, which
both feeds use.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Pool

WARN_PCT = 15.0  # |delta| at or above this is shown red
NOTE_PCT = 5.0  # ... yellow; below is green


def _pct(other: float, primary: float) -> float | None:
    """(other − primary) / primary in percent; None unless both are positive."""
    if primary <= 0 or other <= 0:
        return None
    return (other / primary - 1) * 100


@dataclass(slots=True, frozen=True)
class Recon:
    other: str  # the source compared against ("krystal" / "rhpools")
    tvl_pct: float | None
    vol24_pct: float | None
    fee24_pct: float | None

    @property
    def deltas(self) -> dict[str, float]:
        out = {"tvl": self.tvl_pct, "vol24": self.vol24_pct, "fee24": self.fee24_pct}
        return {k: v for k, v in out.items() if v is not None}

    @property
    def worst(self) -> float | None:
        """Largest absolute disagreement across the comparable metrics."""
        d = self.deltas
        return max(abs(v) for v in d.values()) if d else None

    @property
    def level(self) -> str:
        """'ok' | 'note' | 'warn' | 'none' for colouring."""
        w = self.worst
        if w is None:
            return "none"
        return "warn" if w >= WARN_PCT else "note" if w >= NOTE_PCT else "ok"

    @property
    def headline(self) -> str:
        """Short cell text: the TVL delta, else the first available one."""
        d = self.deltas
        if not d:
            return "?"
        key = "tvl" if "tvl" in d else next(iter(d))
        return f"{d[key]:+.0f}%" + ("" if key == "tvl" else key[0])

    def describe(self) -> str:
        d = self.deltas
        if not d:
            return f"vs {self.other}: nothing comparable"
        return f"vs {self.other}: " + "  ".join(f"{k} {v:+.0f}%" for k, v in d.items())


@dataclass(slots=True)
class Reconciliation:
    other: str
    by_address: dict[str, Recon]
    primary_only: int  # primary pools the other feed does not list
    other_only: int

    def get(self, p: Pool) -> Recon | None:
        return self.by_address.get(p.address)

    @property
    def flagged(self) -> int:
        return sum(1 for r in self.by_address.values() if r.level == "warn")

    def summary(self) -> str:
        return (
            f"vs {self.other}: {len(self.by_address)} matched, {self.flagged} ≥{WARN_PCT:.0f}% off, "
            f"{self.primary_only} only here, {self.other_only} only there"
        )


def reconcile(primary: list[Pool], other: list[Pool]) -> Reconciliation:
    """Deltas of `other` relative to `primary` for every pool both feeds list."""
    other_by = {p.address: p for p in other if p.address}
    other_name = next((p.source for p in other), "other")
    by_address: dict[str, Recon] = {}
    for p in primary:
        o = other_by.get(p.address)
        if o is None:
            continue
        tvl_known = "tvl" not in p.unknown and "tvl" not in o.unknown
        by_address[p.address] = Recon(
            other=other_name,
            tvl_pct=_pct(o.tvl, p.tvl) if tvl_known else None,
            vol24_pct=_pct(o.s24h.volume, p.s24h.volume),
            fee24_pct=_pct(o.s24h.fee, p.s24h.fee),
        )
    matched = set(by_address)
    return Reconciliation(
        other=other_name,
        by_address=by_address,
        primary_only=sum(1 for p in primary if p.address not in matched),
        other_only=sum(1 for a in other_by if a not in matched),
    )
