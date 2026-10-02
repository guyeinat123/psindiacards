from dataclasses import dataclass, field
from typing import Optional


# PSN account regions we buy wallet cards for -> wallet currency
REGIONS = {"IN": "INR", "US": "USD", "JP": "JPY"}
FLAGS = {"IN": "🇮🇳", "US": "🇺🇸", "JP": "🇯🇵"}


@dataclass
class Offer:
    """One purchasable PSN wallet card offer."""
    source: str            # which scraper found it (dlcompare, seagm, ...)
    store: str             # where you'd actually buy it (Eneba, SEAGM, ...)
    face: int              # card value in the region's wallet currency (₹1000, $50, ¥5000)
    price: float           # price in `currency`, incl. fees when known
    currency: str          # ISO code of `price`: INR, MYR, ILS, USD, EUR, NZD
    url: str
    in_stock: bool = True
    extra_fee_pct: float = 0.0   # estimated checkout fee to add on top of `price`
    note: str = ""               # coupon code, seller name, etc.
    region: str = "IN"           # which PSN account the card is for
    # Filled in by pricing.apply()
    effective_ils: Optional[float] = None
    markup_pct: Optional[float] = None

    @property
    def face_currency(self) -> str:
        return REGIONS[self.region]


@dataclass
class SourceResult:
    source: str
    status: str                       # ok | blocked | error | skipped
    offers: list[Offer] = field(default_factory=list)
    error: str = ""
