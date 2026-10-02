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
        if o.currency not in rates:
            continue
        paid = to_ils(o.price, o.currency, rates) * (1 + o.extra_fee_pct / 100)
        o.effective_ils = round(paid * (1 + foreign_fee_pct / 100), 2)
        face_ils = to_ils(o.face_inr, "INR", rates)
        o.markup_pct = round((o.effective_ils / face_ils - 1) * 100, 1)
        if o.markup_pct <= MAX_SANE_MARKUP_PCT:
            priced.append(o)
    return priced


def best_by_denomination(offers: list[Offer], denominations: list[int]) -> dict[int, list[Offer]]:
    """In-stock offers per card value, cheapest first."""
    out: dict[int, list[Offer]] = {}
    for face in denominations:
        rows = [o for o in offers if o.face_inr == face and o.in_stock and o.effective_ils is not None]
        if rows:
            out[face] = sorted(rows, key=lambda o: o.effective_ils)
    return out


def should_alert(best: Offer, last_alerted_ils: Optional[float],
                 max_markup_pct: float, min_improvement_pct: float) -> bool:
    """Alert on a good deal once, then only again if it gets meaningfully cheaper."""
    if best.markup_pct > max_markup_pct:
        return False
    if last_alerted_ils is None:
        return True
    return best.effective_ils <= last_alerted_ils * (1 - min_improvement_pct / 100)
