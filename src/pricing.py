"""Turn raw offers into comparable 'what it really costs me in ILS' numbers."""
from typing import Optional

from src.models import Offer


# Anything this far above face value is a broken listing (seen: K4G ₹8000 card at ₹501,160)
MAX_SANE_MARKUP_PCT = 200


def to_ils(amount: float, currency: str, rates: dict[str, float]) -> float:
    return amount / rates[currency]


def apply(offers: list[Offer], rates: dict[str, float], foreign_fee_pct: float) -> list[Offer]:
    """Set effective_ils and markup_pct on each offer (in place).

    Drops offers in unknown currencies and obviously broken listings.
    """
    priced = []
    for o in offers:
        if o.currency not in rates or o.face_currency not in rates:
            continue
        paid = to_ils(o.price, o.currency, rates) * (1 + o.extra_fee_pct / 100)
        o.effective_ils = round(paid * (1 + foreign_fee_pct / 100), 2)
        face_ils = to_ils(o.face, o.face_currency, rates)
        o.markup_pct = round((o.effective_ils / face_ils - 1) * 100, 1)
        if o.markup_pct <= MAX_SANE_MARKUP_PCT:
            priced.append(o)
    return priced


def best_by_denomination(offers: list[Offer], denominations: list[int],
                         region: str = "IN") -> dict[int, list[Offer]]:
    """In-stock offers per card value for one region, cheapest first."""
    out: dict[int, list[Offer]] = {}
    for face in denominations:
        rows = [o for o in offers if o.region == region and o.face == face
                and o.in_stock and o.effective_ils is not None]
        if rows:
            out[face] = sorted(rows, key=lambda o: o.effective_ils)
    return out


def best_rate(offers: list[Offer], region: str) -> Optional[Offer]:
    """The in-stock card with the lowest markup for a region: what 1 unit of wallet really costs."""
    rows = [o for o in offers if o.region == region and o.in_stock and o.markup_pct is not None]
    return min(rows, key=lambda o: o.markup_pct, default=None)


def should_alert(best: Offer, last_alerted_ils: Optional[float],
                 max_markup_pct: float, min_improvement_pct: float) -> bool:
    """Alert on a good deal once, then only again if it gets meaningfully cheaper."""
    if best.markup_pct > max_markup_pct:
        return False
    if last_alerted_ils is None:
        return True
    return best.effective_ils <= last_alerted_ils * (1 - min_improvement_pct / 100)


def game_decision(current_ils: float, baseline_ils: Optional[float],
                  min_drop_pct: float) -> tuple[bool, float]:
    """(alert?, new baseline). First sighting just records a baseline. A drop of at least
    min_drop_pct below the baseline alerts; a price rise moves the baseline up so the
    next sale alerts again."""
    if baseline_ils is None:
        return False, current_ils
    if current_ils <= baseline_ils * (1 - min_drop_pct / 100):
        return True, current_ils
    return False, max(baseline_ils, current_ils)
