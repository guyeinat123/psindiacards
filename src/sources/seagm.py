"""SEAGM - official-ish reseller, sells India PSN cards close to face value.

The page carries GA4 ecommerce objects: {"item_id":"734-...","item_name":"PSN Card 1000 INR IN",
"price":"57.93","discount":"0.58","currency":"MYR","item_variant":"Available", ...}
Currency follows the visitor's location, so we read it from each item.
"""
import json
import re

from src.config import config
from src.models import Offer
from src.sources.base import BaseSource, Blocked


URL = "https://www.seagm.com/playstation-network-card-psn-india"
ITEM_MARKER = '{"item_id":"734-'


def parse(html: str, fee_pct: float = 0.0) -> list[Offer]:
    dec = json.JSONDecoder()
    offers, seen, i = [], set(), 0
    while (i := html.find(ITEM_MARKER, i)) >= 0:
        item, i = dec.raw_decode(html, i)
        m = re.search(r"(\d+)\s*INR", item.get("item_name", ""))
        if not m or item["item_id"] in seen:
            continue
        seen.add(item["item_id"])
        price = float(item["price"]) - float(item.get("discount") or 0)
        offers.append(Offer(
            source="seagm",
            store="SEAGM",
            face_inr=int(m.group(1)),
            price=round(price, 2),
            currency=item["currency"],
            url=URL,
            in_stock=item.get("item_variant") == "Available",
            extra_fee_pct=fee_pct,
        ))
    if not offers:
        raise Blocked("no PSN items found (layout change or bot check)")
    return offers


class SeagmSource(BaseSource):
    name = "seagm"

    async def fetch(self) -> list[Offer]:
        resp = await self.get(URL)
        return parse(resp.text, config.SEAGM_FEE_PCT)
