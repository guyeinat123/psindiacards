"""Eneba store listing filtered to India. Covers values dlcompare doesn't (500, 1500, 2500...).

The page embeds an Apollo GraphQL cache (<script id="__APOLLO_STATE__">) with
Product entries and their cheapest Auction. Prices are in cents, in the
visitor's currency; the checkout service fee is NOT included (ENEBA_FEE_PCT).
"""
import json
import re

from src.config import config
from src.models import Offer
from src.sources.base import BaseSource, Blocked


URL = "https://www.eneba.com/store/psn-gift-cards?regions[]=india"
STATE_RE = re.compile(r'<script[^>]*id="__APOLLO_STATE__"[^>]*>(.*?)</script>', re.S)


def parse(html: str, fee_pct: float = 0.0) -> list[Offer]:
    m = STATE_RE.search(html)
    if not m:
        raise Blocked("__APOLLO_STATE__ missing (layout change or bot check)")
    state = json.loads(m.group(1))

    offers = []
    for key, prod in state.items():
        if not key.startswith("Product:"):
            continue
        if [r.get("code") for r in prod.get("regions") or []] != ["india"]:
            continue
        face = re.search(r"Rs\.?\s*(\d+)", prod.get("name", ""))
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
            face_inr=int(face.group(1)),
            price=money["amount"] / 100,
            currency=money["currency"],
            url=f"https://www.eneba.com/{prod['slug']}",
            in_stock=bool(auction.get("isInStock")),
            extra_fee_pct=fee_pct,
            note=f"seller {seller}" if seller else "",
        ))
    return offers


class EnebaSource(BaseSource):
    name = "eneba"

    async def fetch(self) -> list[Offer]:
        resp = await self.get(URL)
        return parse(resp.text, config.ENEBA_FEE_PCT)
