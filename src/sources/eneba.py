"""Eneba store listings for India, US and Japan PSN cards.

Each page embeds an Apollo GraphQL cache (<script id="__APOLLO_STATE__">) with
Product entries and their cheapest Auction. Prices are in cents, in the
visitor's currency; the checkout service fee is NOT included (ENEBA_FEE_PCT).
"""
import asyncio
import json
import re

from src.config import config
from src.models import Offer
from src.sources.base import BaseSource, Blocked


BASE = "https://www.eneba.com/store/psn-gift-cards?regions[]="
# region -> (Eneba region code, how the card value appears in the product name)
REGIONS = {
    "IN": ("india", re.compile(r"Rs\.?\s*(\d+)")),
    "US": ("united_states", re.compile(r"(\d+)\s*USD")),
    "JP": ("japan", re.compile(r"(\d+)\s*JPY")),
}
STATE_RE = re.compile(r'<script[^>]*id="__APOLLO_STATE__"[^>]*>(.*?)</script>', re.S)


def parse(html: str, region: str = "IN", fee_pct: float = 0.0) -> list[Offer]:
    m = STATE_RE.search(html)
    if not m:
        raise Blocked("__APOLLO_STATE__ missing (layout change or bot check)")
    state = json.loads(m.group(1))
    code, face_re = REGIONS[region]

    offers = []
    for key, prod in state.items():
        if not key.startswith("Product:"):
            continue
        if [r.get("code") for r in prod.get("regions") or []] != [code]:
            continue
        face = face_re.search(prod.get("name", ""))
        ref = (prod.get("cheapestAuction") or {}).get("__ref")
        auction = state.get(ref) if ref else None
        if not face or not auction:
            continue
        money = next((v for k, v in auction.items() if k.startswith("price(") and v), None)
        if not money:
            continue
        seller = (auction.get("merchant") or {}).get("displayname", "")
        offers.append(Offer(
            source="eneba",
            store="Eneba",
            face=int(face.group(1)),
            price=money["amount"] / 100,
            currency=money["currency"],
            url=f"https://www.eneba.com/{prod['slug']}",
            in_stock=bool(auction.get("isInStock")),
            extra_fee_pct=fee_pct,
            note=f"seller {seller}" if seller else "",
            region=region,
        ))
    return offers


class EnebaSource(BaseSource):
    name = "eneba"

    async def fetch(self) -> list[Offer]:
        offers = []
        for i, (region, (code, _)) in enumerate(REGIONS.items()):
            if i:
                await asyncio.sleep(2)   # Eneba rate-limits (HTTP 429) rapid page loads
            resp = await self.get(BASE + code)
            offers += parse(resp.text, region, config.ENEBA_FEE_PCT)
        return offers
