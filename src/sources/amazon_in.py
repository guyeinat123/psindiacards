"""Amazon.in via the Keepa API.

Amazon blocks automated page fetches (it serves a "To discuss automated access..."
page), so we don't scrape it. Keepa is a paid, legitimate price-history API
that covers amazon.in (domain 10). Needs KEEPA_API_KEY + AMAZON_ASINS.
"""
from src.config import config
from src.models import Offer
from src.sources.base import BaseSource, Skipped


KEEPA_URL = "https://api.keepa.com/product"
AMAZON_IN = 10
AMAZON, NEW = 0, 1   # indexes into Keepa's stats.current price-type array


def parse(data: dict, asin_to_face: dict[str, int]) -> list[Offer]:
    offers = []
    for p in data.get("products") or []:
        face = asin_to_face.get(p.get("asin"))
        current = ((p.get("stats") or {}).get("current")) or []
        if not face or not current:
            continue
        # Keepa prices are in paise; -1 means no offer right now
        prices = [current[i] for i in (AMAZON, NEW) if len(current) > i and current[i] > 0]
        offers.append(Offer(
            source="amazon_in",
            store="Amazon.in",
            face=face,
            price=min(prices) / 100 if prices else float(face),
            currency="INR",
            url=f"https://www.amazon.in/dp/{p['asin']}",
            in_stock=bool(prices),
        ))
    return offers


class AmazonInSource(BaseSource):
    name = "amazon_in"

    async def fetch(self) -> list[Offer]:
        if not config.KEEPA_API_KEY or not config.AMAZON_ASINS:
            raise Skipped("KEEPA_API_KEY / AMAZON_ASINS not set")
        asin_to_face = {asin: face for face, asin in config.AMAZON_ASINS.items()}
        resp = await self.get(KEEPA_URL, params={
            "key": config.KEEPA_API_KEY,
            "domain": AMAZON_IN,
            "asin": ",".join(asin_to_face),
            "stats": 1,
        })
        return parse(resp.json(), asin_to_face)
