"""dlcompare.in - price comparison across keyshops (Eneba, Kinguin, GAMESEAL, HRK, K4G, Eldorado).

The page embeds `window.priceListData = {...}` with every offer, its
denomination ("specials") and the price including each payment method's fee.
"""
import json
import re

from src.models import Offer
from src.sources.base import BaseSource, Blocked


URL = "https://www.dlcompare.in/gamecards/500/buy-playstation-gift-cards-inr-cd-key"
CREDIT_CARD = "2"   # paymentMethods: {"1": "Paypal", "2": "Credit Card"}


def parse(html: str) -> list[Offer]:
    start = html.find("window.priceListData")
    if start < 0:
        raise Blocked("priceListData missing (layout change or bot check)")
    data, _ = json.JSONDecoder().raw_decode(html, html.index("{", start))

    face_by_special = {}
    for sid, special in data["specials"].items():
        m = re.match(r"(\d+)\s*INR", special["title"])
        if m:
            face_by_special[int(sid)] = int(m.group(1))

    offers = []
    for p in data["prices"]:
        if p.get("displayRegion") != "India" or p.get("isAccountSelling"):
            continue   # "Asia" cards don't redeem on an Indian account
        faces = [face_by_special[s] for s in p.get("specialIds") or [] if s in face_by_special]
        if not faces:
            continue
        shop = data["shops"].get(str(p["shopId"]), {}).get("name", f"shop {p['shopId']}")
        fee_price = (p.get("feePrices") or {}).get(CREDIT_CARD)
        code = p.get("discountCode")
        offers.append(Offer(
            source="dlcompare",
            store=shop,
            face=faces[0],
            price=float(fee_price or p["finalPrice"]),
            currency="INR",
            url=f"https://www.dlcompare.in/price/{p['id']}/serve",
            in_stock=not p.get("unavailableLabel"),
            note=f"coupon {code}" if code else "",
        ))
    return offers


class DlcompareSource(BaseSource):
    name = "dlcompare"

    async def fetch(self) -> list[Offer]:
        resp = await self.get(URL)
        return parse(resp.text)
