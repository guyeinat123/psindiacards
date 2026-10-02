"""simplygaming.in - Indian Shopify store selling PSN India cards at face value.

Usually out of stock, so this is mainly a restock watcher. Shopify exposes
/products.json, no HTML parsing needed.
"""
import re

from src.models import Offer
from src.sources.base import BaseSource


BASE = "https://www.simplygaming.in"
URL = f"{BASE}/collections/playstation-gift-cards-india/products.json?limit=100"


def parse(data: dict) -> list[Offer]:
    offers = []
    for p in data.get("products", []):
        m = re.search(r"₹\s*([\d,]+)", p.get("title", ""))
        if not m:
            continue
        face = int(m.group(1).replace(",", ""))
        for v in p.get("variants", []):
            offers.append(Offer(
                source="simplygaming",
                store="SimplyGaming.in",
                face_inr=face,
                price=float(v["price"]),
                currency="INR",
                url=f"{BASE}/products/{p['handle']}",
                in_stock=bool(v.get("available")),
            ))
    return offers


class SimplygamingSource(BaseSource):
    name = "simplygaming"

    async def fetch(self) -> list[Offer]:
        resp = await self.get(URL)
        return parse(resp.json())
