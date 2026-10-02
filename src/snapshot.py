"""Latest prices as plain JSON (stored in the DB), so Telegram commands answer instantly."""
from typing import Optional

from src.combos import CardOption
from src.games import Comparison
from src.models import REGIONS, Offer
from src.psplus import PlanPrice


def cards_part(offers: list[Offer]) -> dict[str, list[dict]]:
    """region -> cheapest in-stock offer per card value."""
    best: dict[tuple[str, int], Offer] = {}
    for o in offers:
        if not o.in_stock or o.effective_ils is None:
            continue
        key = (o.region, o.face)
        if key not in best or o.effective_ils < best[key].effective_ils:
            best[key] = o
    out: dict[str, list[dict]] = {r: [] for r in REGIONS}
    for (region, face), o in sorted(best.items()):
        out[region].append({"face": face, "ils": o.effective_ils, "markup": o.markup_pct,
                            "store": o.store, "url": o.url, "note": o.note})
    return out


def plans_part(plans: dict[tuple[str, int], list[PlanPrice]]) -> dict[str, list[dict]]:
    return {f"{tier}:{months}": [
        {"region": p.region, "price": p.price, "base": p.base_price, "currency": p.currency,
         "ils": p.effective_ils} for p in rows]
        for (tier, months), rows in plans.items()}


def game_entry(c: Comparison) -> dict:
    return {"key": c.concept_id, "title": c.title, "edition": c.edition_name, "rows": [
        {"region": r.region, "price": r.edition.price, "base": r.edition.base_price,
         "currency": r.edition.currency, "ils": r.effective_ils, "url": r.url} for r in c.rows]}


def card_options(snap: dict, region: str) -> list[CardOption]:
    return [CardOption(c["face"], c["ils"], c["store"], c["url"], c.get("note", ""))
            for c in snap.get("cards", {}).get(region, [])]


def wallet_costs(snap: dict) -> dict[str, float]:
    """region -> real ₪ per 1 unit of wallet, from the best card in the snapshot."""
    out = {}
    for region, cards in snap.get("cards", {}).items():
        if cards:
            out[region] = min(c["ils"] / c["face"] for c in cards)
    return out


def best_card(snap: dict, region: str) -> Optional[dict]:
    cards = snap.get("cards", {}).get(region) or []
    return min(cards, key=lambda c: c["markup"], default=None)
