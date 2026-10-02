"""egiftcards.nz - NZ gift card shop, sells PSN India at ~+5% over face value (NZD).

All card values are variations of one WooCommerce product; the product page
embeds them as JSON in the add-to-cart form's data-product_variations attribute.
"""
import html
import json
import re
from urllib.parse import unquote

from src.models import Offer
from src.sources.base import BaseSource, Blocked


URL = "https://www.egiftcards.nz/product/playstation-gift-cards-india-region-inr-email-delivery/"
VARIATIONS_RE = re.compile(r'data-product_variations="([^"]*)"')
SMALL_STORE = "⚠️ חנות קטנה (2.8 בטראסטפיילוט) - לנסות קודם ₹1,000"


def parse(page: str) -> list[Offer]:
    m = VARIATIONS_RE.search(page)
    if not m:
        raise Blocked("data-product_variations missing (layout change or bot check)")
    offers = []
    for v in json.loads(html.unescape(m.group(1))):
        # attribute values are URL-encoded: "%e2%82%b91000-inr" -> "₹1000-inr"
        amount = unquote(next(iter(v.get("attributes", {}).values()), ""))
        face = re.search(r"₹(\d+)-inr", amount)
        if not face:
            continue
        offers.append(Offer(
            source="egiftcards_nz",
            store="egiftcards.nz",
            face=int(face.group(1)),
            price=float(v["display_price"]),
            currency="NZD",
            url=URL,
            in_stock=bool(v.get("is_in_stock")),
            note=SMALL_STORE,
        ))
    return offers


class EgiftcardsNzSource(BaseSource):
    name = "egiftcards_nz"

    async def fetch(self) -> list[Offer]:
        resp = await self.get(URL)
        return parse(resp.text)
