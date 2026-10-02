"""SEAGM - reliable reseller with India and Japan PSN cards.

The pages carry GA4 ecommerce objects: {"item_id":"734-...","item_name":"PSN Card 1000 INR IN",
"price":"57.93","discount":"0.58","currency":"MYR","item_variant":"Available", ...}
Currency follows the visitor's location, so we read it from each item.
"""
import json
import re

from src.config import config
from src.models import Offer
from src.sources.base import BaseSource, Blocked


PAGES = {
    "IN": "https://www.seagm.com/playstation-network-card-psn-india",
    "JP": "https://www.seagm.com/playstation-network-card-psn-japan",
}
FACE_RE = {"IN": re.compile(r"(\d+)\s*INR"), "JP": re.compile(r"(\d+)\s*Yen")}
ITEM_MARKER = '{"item_id":"'


def parse(html: str, region: str = "IN", fee_pct: float = 0.0) -> list[Offer]:
    dec = json.JSONDecoder()
    offers, seen, i = [], set(), 0
    while (i := html.find(ITEM_MARKER, i)) >= 0:
        item, i = dec.raw_decode(html, i)
        m = FACE_RE[region].search(item.get("item_name", ""))
        if not m or item["item_id"] in seen:
            continue
        seen.add(item["item_id"])
        price = float(item["price"]) - float(item.get("discount") or 0)
        offers.append(Offer(
            source="seagm",
            store="SEAGM",
            face=int(m.group(1)),
            price=round(price, 2),
            currency=item["currency"],
            url=PAGES[region],
            in_stock=item.get("item_variant") == "Available",
            extra_fee_pct=fee_pct,
            region=region,
        ))
    if not offers:
        raise Blocked(f"no PSN {region} items found (layout change or bot check)")
    return offers


class SeagmSource(BaseSource):
    name = "seagm"

    async def fetch(self) -> list[Offer]:
        offers = []
        for region, url in PAGES.items():
            resp = await self.get(url)
            offers += parse(resp.text, region, config.SEAGM_FEE_PCT)
        return offers
