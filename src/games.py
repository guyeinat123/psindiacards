"""Compare a game's price across the India / US / Japan PlayStation Stores, in real ₪.

For each watched game (a PS Store concept) we read the store page in every
region. Each edition is a Product whose id ends in a region-independent label
(UP0002-PPSA01649_00-CODMW4STANDARD01 vs EP0002-PPSA07950_00-CODMW4STANDARD01),
so the same edition can be matched across stores. The page embeds the data in
<script id="env:..."> JSON blobs: Product entries reference GameCTA entries,
and each GameCTA carries a Price.

Real cost = store price × what 1 unit of that region's wallet costs you
(best gift card markup, incl. fees and bank fee) converted to ₪.
"""
import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from src.models import REGIONS
from src.sources.base import Blocked


LOCALES = {"IN": "en-in", "US": "en-us", "JP": "ja-jp"}
CONCEPT_URL = "https://store.playstation.com/{locale}/concept/{cid}"
PRODUCT_URL = "https://store.playstation.com/en-us/product/{pid}"
ENV_RE = re.compile(r'<script id="env:[^"]+"[^>]*>(.*?)</script>', re.S)


@dataclass
class Edition:
    label: str          # region-independent edition id, e.g. CODMW4STANDARD01
    name: str           # "MW4 Standard"
    price: float        # in wallet currency
    base_price: float
    currency: str


@dataclass
class RegionPrice:
    region: str
    edition: Edition
    effective_ils: float
    url: str


@dataclass
class Comparison:
    concept_id: str
    title: str
    edition_name: str
    rows: list[RegionPrice] = field(default_factory=list)   # cheapest first

    @property
    def best(self) -> RegionPrice:
        return self.rows[0]


def _decimals(display: str) -> int:
    """'$69.99' -> 2, 'Rs 5,999' -> 0, '¥9,800' -> 0"""
    return 2 if re.search(r"\.\d{2}\s*$", display.strip()) else 0


def _price_of(cta: dict) -> Optional[tuple[float, float, str]]:
    p = cta.get("price") or {}
    if (p.get("isFree") or p.get("isTiedToSubscription") or not p.get("discountedValue")
            or p.get("applicability") not in (None, "APPLICABLE")):
        return None
    div = 10 ** _decimals(p.get("basePrice") or "")
    return p["discountedValue"] / div, p["basePriceValue"] / div, p["currencyCode"]


def _merge(dst: dict, src: dict) -> None:
    """Blobs repeat entries with different fields filled in; keep every non-null value."""
    for key, val in src.items():
        if isinstance(val, dict) and isinstance(dst.get(key), dict):
            _merge(dst[key], val)
        elif val is not None or key not in dst:
            dst[key] = val


def _walk(node):
    """Yield every dict nested anywhere in a JSON value."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _sku_of(cta: dict) -> Optional[str]:
    for param in (cta.get("action") or {}).get("param") or []:
        if param.get("name") == "skuId":
            return param.get("value")
    return None


def parse_concept(html: str) -> tuple[str, dict[str, Edition]]:
    """Returns (title, {edition label: cheapest purchasable price}).

    Prices live on GameCTA objects (sometimes referenced, sometimes inline, sometimes
    only filled in in a later blob), so we scan every CTA and key it by its SKU's label.
    """
    cache: dict = {}
    for blob in ENV_RE.findall(html):
        if "GameCTA" in blob:
            _merge(cache, json.loads(blob).get("cache") or {})
    if not cache:
        raise Blocked("no product data on page (not sold here, layout change or bot check)")

    title, names = "", {}
    for key, prod in cache.items():
        if key.startswith("Product:") and len(prod.get("id", "").split("-")) >= 3:
            label = prod["id"].split("-")[2]
            title = title or prod.get("name", "")
            ed_name = (prod.get("edition") or {}).get("name")
            if ed_name or label not in names:
                names[label] = ed_name or prod.get("name", label)

    editions: dict[str, Edition] = {}
    for cta in _walk(cache):
        if cta.get("__typename") != "GameCTA":
            continue
        sku, got = _sku_of(cta), _price_of(cta)
        if not sku or not got or len(sku.split("-")) < 3:
            continue
        label = sku.split("-")[2]
        if label not in editions or got[0] < editions[label].price:
            editions[label] = Edition(label, names.get(label, label), got[0], got[1], got[2])
    return title, editions


def concept_id_from(line: str, product_html: Optional[str] = None) -> Optional[str]:
    """games.txt line -> concept id. Accepts a concept URL, a bare id, or (with its page) a product URL."""
    if m := re.search(r"/concept/(\d+)", line):
        return m.group(1)
    if re.fullmatch(r"\d+", line):
        return line
    if product_html and (m := re.search(r'"conceptId","value":"(\d+)"', product_html)):
        return m.group(1)
    return None


def read_watchlist(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    lines = [l.split("#", 1)[0].strip() for l in p.read_text().splitlines()]
    return [l for l in lines if l]


def compare(concept_id: str, pages: dict[str, tuple[str, dict[str, Edition]]],
            wallet_ils: dict[str, float]) -> Optional[Comparison]:
    """pages: region -> parsed concept page. wallet_ils: region -> real ₪ per 1 unit of wallet."""
    pages = {r: p for r, p in pages.items() if p[1] and r in wallet_ils}
    if not pages:
        return None
    # The edition sold in the most regions; among those, the cheapest - preferring a
    # "Standard" edition (some concepts, e.g. Call of Duty, also list older games).
    labels = {lab for _, eds in pages.values() for lab in eds}
    standard = {lab for lab in labels if "STANDARD" in lab.upper()}
    labels = standard or labels
    def key(lab):
        regions = [r for r in pages if lab in pages[r][1]]
        cheapest = min(pages[r][1][lab].price * wallet_ils[r] for r in regions)
        return (-len(regions), cheapest)
    label = min(labels, key=key)

    title = pages.get("US", pages.get("IN", next(iter(pages.values()))))[0]
    rows = []
    for region, (_, eds) in pages.items():
        if ed := eds.get(label):
            url = CONCEPT_URL.format(locale=LOCALES[region], cid=concept_id)
            rows.append(RegionPrice(region, ed, round(ed.price * wallet_ils[region], 2), url))
    rows.sort(key=lambda r: r.effective_ils)
    edition_name = next(eds[label].name for _, eds in pages.values() if label in eds)
    return Comparison(concept_id, title, edition_name, rows)


async def fetch_game(client: httpx.AsyncClient, line: str,
                     wallet_ils: dict[str, float]) -> Optional[Comparison]:
    product_html = None
    if "/product/" in line:
        pid = line.rstrip("/").split("/product/")[1].split("?")[0]
        product_html = (await client.get(PRODUCT_URL.format(pid=pid))).text
    cid = concept_id_from(line, product_html)
    if not cid:
        raise ValueError(f"can't find a game id in {line!r}")

    async def one(region: str):
        resp = await client.get(CONCEPT_URL.format(locale=LOCALES[region], cid=cid))
        if resp.status_code == 404:
            return region, ("", {})          # not sold in this region
        if resp.status_code in (403, 429, 503):
            raise Blocked(f"PS Store {region} HTTP {resp.status_code}")
        resp.raise_for_status()
        try:
            return region, parse_concept(resp.text)
        except Blocked:
            return region, ("", {})
    pages = dict(await asyncio.gather(*(one(r) for r in LOCALES)))
    return compare(cid, pages, wallet_ils)


def wallet_costs(best_cards: dict, rates: dict[str, float]) -> dict[str, float]:
    """region -> real ₪ you pay per 1 unit of that wallet (e.g. per $1), from the best card."""
    out = {}
    for region, offer in best_cards.items():
        if offer is not None:
            out[region] = (1 + offer.markup_pct / 100) / rates[REGIONS[region]]
    return out
