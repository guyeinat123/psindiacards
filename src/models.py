from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Offer:
    """One purchasable PSN India card offer."""
    source: str            # which scraper found it (dlcompare, seagm, ...)
    store: str             # where you'd actually buy it (Eneba, SEAGM, ...)
    face_inr: int          # card value in rupees
    price: float           # price in `currency`, incl. fees when fee_included
    currency: str          # ISO code: INR, MYR, ILS, USD, EUR
    url: str
    in_stock: bool = True
    extra_fee_pct: float = 0.0   # estimated checkout fee to add on top of `price`
    note: str = ""               # coupon code, seller name, etc.
    # Filled in by pricing.apply()
    effective_ils: Optional[float] = None
    markup_pct: Optional[float] = None


@dataclass
class SourceResult:
    source: str
    status: str                       # ok | blocked | error | skipped
    offers: list[Offer] = field(default_factory=list)
    error: str = ""
