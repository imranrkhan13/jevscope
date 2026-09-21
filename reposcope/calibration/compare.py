"""Head-to-head comparison on identical items.

The comparison is paired: both providers see the same FileState for the same
file, so differences are not confounded by sampling. That permits McNemar's
test, which asks the only question that matters — of the items where the two
disagree, is the split lopsided enough to be more than noise?

Reporting "Jev 84%, LLM 87%" on 200 items without this is reporting a coin
flip. The discordant counts are usually small even when the accuracy gap looks
meaningful.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Paired:
    key: str
    gold: str
    a_pred: str
    b_pred: str
    a_certainty: float
    b_certainty: float
    a_latency_ms: float
    b_latency_ms: float
    a_cost_usd: float
    b_cost_usd: float

    @property
    def a_correct(self) -> bool:
        return self.a_pred == self.gold

    @property
    def b_correct(self) -> bool:
        return self.b_pred == self.gold


@dataclass(frozen=True)
class McNemar:
    #: a right, b wrong
    a_only: int
    #: b right, a wrong
    b_only: int
    both: int
    neither: int
    statistic: float
    p_value: float
    exact: bool

    @property
    def discordant(self) -> int:
        return self.a_only + self.b_only

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05

    def verdict(self, a_name: str, b_name: str) -> str:
        if self.discordant < 10:
            return (
                f"Only {self.discordant} discordant items — too few to distinguish "
                f"{a_name} from {b_name}. Label more data before claiming a winner."
            )
        if not self.significant:
            return (
                f"No significant difference (p={self.p_value:.3f}, "
                f"{self.discordant} discordant)."
            )
        winner, loser = (a_name, b_name) if self.a_only > self.b_only else (b_name, a_name)
        return f"{winner} beats {loser} (p={self.p_value:.3f}, {self.discordant} discordant)."


def _binom_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial test at p=0.5. Used when the normal
    approximation is not safe, which is most small eval sets."""
    if n == 0:
        return 1.0
    k = min(k, n - k)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2**n)
    return min(1.0, 2 * tail)


def mcnemar(pairs: list[Paired]) -> McNemar:
    a_only = sum(1 for p in pairs if p.a_correct and not p.b_correct)
    b_only = sum(1 for p in pairs if p.b_correct and not p.a_correct)
    both = sum(1 for p in pairs if p.a_correct and p.b_correct)
    neither = sum(1 for p in pairs if not p.a_correct and not p.b_correct)
    n = a_only + b_only

    # Below 25 discordant pairs the chi-square approximation is unreliable.
    if n < 25:
        return McNemar(
            a_only, b_only, both, neither,
            statistic=float(min(a_only, b_only)),
            p_value=_binom_two_sided(min(a_only, b_only), n),
            exact=True,
        )

    # Continuity-corrected chi-square, 1 df.
    stat = (abs(a_only - b_only) - 1) ** 2 / n
    p = math.erfc(math.sqrt(stat / 2))
    return McNemar(a_only, b_only, both, neither, statistic=stat, p_value=p, exact=False)


@dataclass(frozen=True)
class ProviderStats:
    name: str
    n: int
    accuracy: float
    mean_latency_ms: float
    p95_latency_ms: float
    total_cost_usd: float
    cost_per_correct: float

    @property
    def cost_per_1k(self) -> float:
        return (self.total_cost_usd / self.n * 1000) if self.n else 0.0


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(q * len(ordered)))
    return ordered[idx]


def provider_stats(pairs: list[Paired], which: str, name: str) -> ProviderStats:
    n = len(pairs)
    if which == "a":
        correct = sum(1 for p in pairs if p.a_correct)
        lat = [p.a_latency_ms for p in pairs]
        cost = sum(p.a_cost_usd for p in pairs)
    else:
        correct = sum(1 for p in pairs if p.b_correct)
        lat = [p.b_latency_ms for p in pairs]
        cost = sum(p.b_cost_usd for p in pairs)

    return ProviderStats(
        name=name,
        n=n,
        accuracy=correct / n if n else 0.0,
        mean_latency_ms=sum(lat) / n if n else 0.0,
        p95_latency_ms=_percentile(lat, 0.95),
        total_cost_usd=cost,
        cost_per_correct=cost / correct if correct else float("inf"),
    )
