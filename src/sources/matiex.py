"""Matiex Store - small WooCommerce shop. India cards near face value (often sold out),
US cards ~5-7% BELOW face value.

WooCommerce's public Store API returns prices (in minor units) and stock as JSON.
"""
import html
import re

from src.models import Offer
from src.sources.base import BaseSource


URL = "https://matiexstore.com/wp-json/wc/store/v1/products"
PARAMS = {"search": "playstation", "per_page": 100}
SMALL_STORE = "⚠️ חנות קטנה - לנסות קודם כרטיס קטן"
# product name patterns -> region
PATTERNS = [
    ("IN", re.compile(r"Gift Card India\s*₹\s*([\d,]+)")),
    ("US", re.compile(r"Wallet \| US – \$(\d+)")),
]


def parse(products: list[dict]) -> list[Offer]:
    offers = []
    for p in products:
        name = html.unescape(p.get("name", ""))
        for region, pattern in PATTERNS:
            m = pattern.search(name)
            if not m:
                continue
            prices = p["prices"]
            offers.append(Offer(
                source="matiex",
                store="Matiex Store",
                face=int(m.group(1).replace(",", "")),
                price=int(prices["price"]) / 10 ** prices["currency_minor_unit"],
                currency=prices["currency_code"],
                url=p["permalink"],
                in_stock=bool(p.get("is_in_stock")),
                note=SMALL_STORE,
                region=region,
            ))
    return offers


class MatiexSource(BaseSource):
    name = "matiex"

    async def fetch(self) -> list[Offer]:
        resp = await self.get(URL, params=PARAMS)
        return parse(resp.json())
