"""PS Plus prices on the India / US / Japan stores, in real ₪ (store price × wallet card cost).

playstation.com/<locale>/ps-plus/ embeds every plan as a SKU like
IP9105-PPSA07181_00-PLUS2T12M0000000-J002 (tier 2 = Extra, 12 months),
each followed by a SubscriptionPrice with base and discounted value.
"""
import asyncio
import html
import json
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from src.models import REGIONS
from src.sources.base import Blocked


LOCALES = {"IN": "en-in", "US": "en-us", "JP": "ja-jp"}
PAGE_URL = "https://www.playstation.com/{locale}/ps-plus/"
TIERS = {"1": "Essential", "2": "Extra", "3": "Premium"}    # India calls tier 3 "Deluxe"
SKU_RE = re.compile(r'"skuId":"[A-Z0-9_]+-[A-Z0-9_]+-PLUS(\d)T(\d\d)M\d*-[A-Z0-9]+"')
DECIMALS = {"USD": 2}


@dataclass
class PlanPrice:
    region: str
    tier: str
    months: int
    price: float          # wallet currency, after any sale
    base_price: float
    currency: str
    effective_ils: Optional[float] = None

    @property
    def on_sale(self) -> bool:
        return self.price < self.base_price


def parse(page: str, region: str) -> dict[tuple[str, int], PlanPrice]:
    page = html.unescape(page)
    dec, plans = json.JSONDecoder(), {}
    for m in SKU_RE.finditer(page):
        j = page.find('"price":{', m.end())
        if j < 0 or j - m.end() > 3000:
            continue
        p, _ = dec.raw_decode(page, j + 8)
        if p.get("__typename") != "SubscriptionPrice" or not p.get("discountedValue"):
            continue
        tier, months = TIERS.get(m.group(1)), int(m.group(2))
        if not tier:
            continue
        cur = p["currencyCode"]
        div = 10 ** DECIMALS.get(cur, 0)
        plan = PlanPrice(region, tier, months, p["discountedValue"] / div, p["basePriceValue"] / div, cur)
        key = (tier, months)
        if key not in plans or plan.price < plans[key].price:
            plans[key] = plan
    if not plans:
        raise Blocked(f"no PS Plus prices on {region} page (layout change or bot check)")
    if any(p.currency != REGIONS[region] for p in plans.values()):
        raise ValueError(f"unexpected currency on {region} PS Plus page")
    return plans


async def fetch_all(client: httpx.AsyncClient,
                    wallet_ils: dict[str, float]) -> dict[tuple[str, int], list[PlanPrice]]:
    """(tier, months) -> plan in each region, cheapest real ₪ first."""
    async def one(region):
        resp = await client.get(PAGE_URL.format(locale=LOCALES[region]))
        resp.raise_for_status()
        return parse(resp.text, region)
    regions = [r for r in LOCALES if r in wallet_ils]
    pages = await asyncio.gather(*(one(r) for r in regions))
    out: dict[tuple[str, int], list[PlanPrice]] = {}
    for region, plans in zip(regions, pages):
        for key, plan in plans.items():
            plan.effective_ils = round(plan.price * wallet_ils[region], 2)
            out.setdefault(key, []).append(plan)
    for rows in out.values():
        rows.sort(key=lambda p: p.effective_ils)
    return out


def plan_url(region: str) -> str:
    return PAGE_URL.format(locale=LOCALES[region])
