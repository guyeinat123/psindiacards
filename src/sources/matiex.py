"""Matiex Store - small WooCommerce shop, sells PSN India near face value (~+10%) but often sold out.

WooCommerce's public Store API returns prices (in minor units) and stock as JSON.
"""
import re

from src.models import Offer
from src.sources.base import BaseSource


URL = "https://matiexstore.com/wp-json/wc/store/v1/products"
PARAMS = {"search": "Playstation Gift Card India", "per_page": 50}
SMALL_STORE = "⚠️ חנות קטנה - לנסות קודם ₹1,000"


def parse(products: list[dict]) -> list[Offer]:
    offers = []
    for p in products:
        m = re.search(r"India\s*₹\s*([\d,]+)", p.get("name", ""))
        if not m:
            continue
        prices = p["prices"]
        offers.append(Offer(
            source="matiex",
            store="Matiex Store",
            face_inr=int(m.group(1).replace(",", "")),
            price=int(prices["price"]) / 10 ** prices["currency_minor_unit"],
            currency=prices["currency_code"],
            url=p["permalink"],
            in_stock=bool(p.get("is_in_stock")),
            note=SMALL_STORE,
        ))
    return offers


class MatiexSource(BaseSource):
    name = "matiex"

    async def fetch(self) -> list[Offer]:
        resp = await self.get(URL, params=PARAMS)
        return parse(resp.json())
