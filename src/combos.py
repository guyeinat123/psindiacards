"""Cheapest combination of wallet cards that covers a price.

E.g. PS Plus Extra in Japan costs ¥11,700: with ¥5,000 at +11% and ¥1,100 at +16%,
the cheapest cover is 2×¥5,000 + 2×¥1,100 = ¥12,200 (¥500 stays in the wallet).
"""
from dataclasses import dataclass
from functools import reduce
from math import gcd
from typing import Optional


@dataclass
class CardOption:
    face: int
    cost_ils: float
    store: str
    url: str
    note: str = ""


@dataclass
class Combo:
    picks: list[tuple[CardOption, int]]     # (card, how many)
    total_face: int
    total_ils: float

    def leftover(self, price: float) -> float:
        return self.total_face - price


def cheapest_cover(price: float, options: list[CardOption]) -> Optional[Combo]:
    """Min-cost multiset of cards whose faces sum to >= price (ties: less left over)."""
    options = [o for o in options if o.face > 0]
    if not options or price <= 0:
        return None
    step = reduce(gcd, (o.face for o in options))
    need = -(-int(round(price * 100)) // (step * 100))          # ceil(price / step), price may be $79.99
    top = need + max(o.face for o in options) // step
    INF = float("inf")
    best = [INF] * (top + 1)            # best[k] = min cost to reach exactly k*step
    choice: list[Optional[int]] = [None] * (top + 1)
    best[0] = 0.0
    for k in range(1, top + 1):
        for i, o in enumerate(options):
            u = o.face // step
            if u <= k and best[k - u] + o.cost_ils < best[k]:
                best[k], choice[k] = best[k - u] + o.cost_ils, i
    k = min(range(need, top + 1), key=lambda j: (round(best[j], 6), j))
    if best[k] == INF:
        return None
    counts: dict[int, int] = {}
    total_ils, j = best[k], k
    while j > 0:
        i = choice[j]
        counts[i] = counts.get(i, 0) + 1
        j -= options[i].face // step
    picks = sorted(((options[i], n) for i, n in counts.items()), key=lambda p: -p[0].face)
    return Combo(picks, k * step, round(total_ils, 2))
