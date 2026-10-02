"""dlcompare - price comparison across keyshops (Eneba, Kinguin, GAMESEAL, HRK, K4G, Eldorado).

The page embeds `window.priceListData = {...}` with every offer, its card value
("specials") and the price including each payment method's fee. The prices
already include the shop coupon shown in `discountCode` - enter it at checkout.
"""
import json
import re

from src.models import Offer
from src.sources.base import BaseSource, Blocked


# region -> (page, displayRegion to keep, card value pattern)
PAGES = {
    "IN": ("https://www.dlcompare.in/gamecards/500/buy-playstation-gift-cards-inr-cd-key",
           "India", re.compile(r"(\d+)\s*INR")),
    "JP": ("https://www.dlcompare.com/gamecards/597/buy-playstation-gift-cards-jpy",
           "Japan", re.compile(r"(\d+)\s*JPY")),
}
CREDIT_CARD = "2"   # paymentMethods: {"1": "Paypal", "2": "Credit Card"}
CURRENCY_BY_SYMBOL = {"&#8377;": "INR", "&#36;": "USD", "&#8364;": "EUR", "&#163;": "GBP"}


def parse(html: str, region: str = "IN") -> list[Offer]:
    _, keep_region, face_re = PAGES[region]
    start = html.find("window.priceListData")
    if start < 0:
        raise Blocked("priceListData missing (layout change or bot check)")
    data, _ = json.JSONDecoder().raw_decode(html, html.index("{", start))
    currency = CURRENCY_BY_SYMBOL.get((data.get("currency") or {}).get("html"))
    if not currency:
        raise ValueError(f"unknown dlcompare currency {data.get('currency')}")

    face_by_special = {}
    for sid, special in data["specials"].items():
        m = face_re.match(special["title"])
        if m:
            face_by_special[int(sid)] = int(m.group(1))

    offers = []
    for p in data["prices"]:
        if p.get("displayRegion") != keep_region or p.get("isAccountSelling"):
            continue   # e.g. "Asia" cards don't redeem on an Indian account
        faces = [face_by_special[s] for s in p.get("specialIds") or [] if s in face_by_special]
        if not faces:
            continue
        shop = data["shops"].get(str(p["shopId"]), {}).get("name", f"shop {p['shopId']}")
        fee_price = (p.get("feePrices") or {}).get(CREDIT_CARD)
        code = p.get("discountCode")
        base_url = PAGES[region][0].split("/gamecards/")[0]
        offers.append(Offer(
            source="dlcompare",
            store=shop,
            face=faces[0],
            price=float(fee_price or p["finalPrice"]),
            currency=currency,
            url=f"{base_url}/price/{p['id']}/serve",
            in_stock=not p.get("unavailableLabel"),
            note=f"coupon {code}" if code else "",
            region=region,
        ))
    return offers


class DlcompareSource(BaseSource):
    name = "dlcompare"

    async def fetch(self) -> list[Offer]:
        offers = []
        for region, (url, _, _) in PAGES.items():
            resp = await self.get(url)
            offers += parse(resp.text, region)
        return offers
