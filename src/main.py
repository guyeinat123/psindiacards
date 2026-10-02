"""PSN wallet card + game price scout (India / US / Japan accounts).

    python -m src.main run-once [--dry-run] [--only seagm,eneba]   # card deals (India)
    python -m src.main games [--dry-run] [--force]                  # watched games, cheapest account
    python -m src.main summary [--dry-run]                          # daily overview
    python -m src.main test-alert
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

from src import games as games_mod
from src import pricing
from src.config import config
from src.db import DB, now_iso
from src.fx import fetch_rates
from src.models import REGIONS, Offer, SourceResult
from src.sources.base import DEFAULT_HEADERS, fetch_all
from src.sources.registry import ALL_SOURCES
from src.telegram_notifier import (TelegramNotifier, format_alert, format_broken,
                                   format_game_alert, format_summary)


log = structlog.get_logger()


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=25.0, follow_redirects=True)


async def collect(client: httpx.AsyncClient, only: Optional[set[str]] = None
                  ) -> tuple[list[SourceResult], list[Offer], dict[str, float]]:
    rates = await fetch_rates(client)
    sources = [cls(client) for cls in ALL_SOURCES if not only or cls.name in only]
    results = await fetch_all(sources)
    offers = [o for r in results for o in r.offers]
    return results, pricing.apply(offers, rates, config.FOREIGN_FEE_PCT), rates


def best_cards_by_region(offers: list[Offer]) -> dict[str, Optional[Offer]]:
    return {region: pricing.best_rate(offers, region) for region in REGIONS}


async def check_games(client: httpx.AsyncClient, offers: list[Offer],
                      rates: dict[str, float]) -> list[games_mod.Comparison]:
    wallet = games_mod.wallet_costs(best_cards_by_region(offers), rates)
    sem = asyncio.Semaphore(3)

    async def one(line: str):
        async with sem:
            try:
                return await games_mod.fetch_game(client, line, wallet)
            except Exception as e:
                log.error("game.failed", game=line, error=f"{type(e).__name__}: {e}")
                return None
    found = await asyncio.gather(*(one(l) for l in games_mod.read_watchlist(config.GAMES_FILE)))
    return [c for c in found if c and c.rows]


def print_table(best: dict[int, list[Offer]], results: list[SourceResult],
                best_cards: dict[str, Optional[Offer]]) -> None:
    for r in results:
        print(f"[{r.status:7}] {r.source:13} {len(r.offers):3} offers {r.error}")
    print()
    for region, o in best_cards.items():
        print(f"{region} wallet: " + (f"{o.markup_pct:+.1f}% via {o.store} {o.face} {o.face_currency}"
                                      if o else "no card in stock"))
    print()
    for face in config.DENOMINATIONS:
        ranked = best.get(face, [])
        print(f"₹{face:>5}: " + ("out of stock everywhere" if not ranked else ""))
        for o in ranked[:4]:
            print(f"         ₪{o.effective_ils:7.2f} {o.markup_pct:+6.1f}%  {o.store:16} "
                  f"{o.price:g} {o.currency} {o.note}")


def print_games(found: list[games_mod.Comparison]) -> None:
    for c in found:
        print(f"\n{c.title} [{c.edition_name}]")
        for r in c.rows:
            print(f"   {r.region} ₪{r.effective_ils:8.2f}  {r.edition.price:g} {r.edition.currency}"
                  + (f" (was {r.edition.base_price:g})" if r.edition.price < r.edition.base_price else ""))


async def run_once(dry_run: bool, only: Optional[set[str]]) -> None:
    async with new_client() as client:
        results, offers, _ = await collect(client, only)
    best = pricing.best_by_denomination(offers, config.DENOMINATIONS, "IN")
    if dry_run:
        print_table(best, results, best_cards_by_region(offers))
        return

    db = DB(config.DATABASE_PATH)
    notifier = TelegramNotifier()
    try:
        db.save_offers(offers, now_iso())
        all_ok = all(r.status in ("ok", "skipped") for r in results)
        for face in config.DENOMINATIONS:
            ranked = best.get(face)
            if not ranked or ranked[0].markup_pct > config.MAX_MARKUP_PCT:
                if all_ok:   # don't forget a deal just because a source hiccuped
                    db.clear_alert(face)
                continue
            top = ranked[0]
            if pricing.should_alert(top, db.last_alert_ils(face),
                                    config.MAX_MARKUP_PCT, config.MIN_IMPROVEMENT_PCT):
                text = format_alert(face, ranked, db.lowest_seen(face))
                if await notifier.send_html(text):
                    db.record_alert(top)
                    log.info("alert.sent", face=face, store=top.store, ils=top.effective_ils)
        for r in results:
            if db.update_health(r, config.BROKEN_AFTER_FAILURES):
                await notifier.send_html(format_broken(r))
    finally:
        db.close()


def games_due(db: DB) -> bool:
    last = db.get_meta("games_last_run")
    if not last:
        return True
    elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
    return elapsed.total_seconds() >= config.GAMES_EVERY_HOURS * 3600 - 15 * 60


async def run_games(dry_run: bool, force: bool) -> None:
    if not games_mod.read_watchlist(config.GAMES_FILE):
        print(f"no games in {config.GAMES_FILE}")
        return
    db = None if dry_run else DB(config.DATABASE_PATH)
    try:
        if db and not force and not games_due(db):
            log.info("games.not_due")
            return
        async with new_client() as client:
            _, offers, rates = await collect(client)
            found = await check_games(client, offers, rates)
        if dry_run:
            print_games(found)
            return
        notifier = TelegramNotifier()
        best_cards = best_cards_by_region(offers)
        for c in found:
            baseline = db.game_baseline(c.concept_id)
            alert, new_baseline = pricing.game_decision(
                c.best.effective_ils, baseline, config.MIN_GAME_DROP_PCT)
            if alert:
                await notifier.send_html(format_game_alert(c, baseline, best_cards))
                log.info("game.alert", game=c.title, region=c.best.region, ils=c.best.effective_ils)
            db.save_game(c.concept_id, c.title, c.best.region, c.best.effective_ils, new_baseline)
        db.set_meta("games_last_run", now_iso())
    finally:
        if db:
            db.close()


async def summary(dry_run: bool) -> None:
    async with new_client() as client:
        results, offers, rates = await collect(client)
        found = await check_games(client, offers, rates)
    best = pricing.best_by_denomination(offers, config.DENOMINATIONS, "IN")
    text = format_summary(best, config.DENOMINATIONS, results, 1000 / rates["INR"],
                          best_cards_by_region(offers), found)
    if dry_run:
        print(text)
        return
    await TelegramNotifier().send_html(text)


async def test_alert() -> None:
    sample = Offer("test", "Test Store", 1000, 1000.0, "INR", "https://example.com",
                   effective_ils=32.70, markup_pct=2.5, note="this is a test")
    ok = await TelegramNotifier().send_html(format_alert(1000, [sample], None))
    print("sent" if ok else "FAILED - check token / chat id")


def main() -> None:
    logging.basicConfig(level=config.LOG_LEVEL, stream=sys.stderr)
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(config.LOG_LEVEL)))
    parser = argparse.ArgumentParser(prog="psn-scout")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run-once")
    p_run.add_argument("--dry-run", action="store_true", help="print prices, no Telegram, no DB")
    p_run.add_argument("--only", help="comma-separated source names")
    p_games = sub.add_parser("games")
    p_games.add_argument("--dry-run", action="store_true")
    p_games.add_argument("--force", action="store_true", help="ignore GAMES_EVERY_HOURS")
    p_sum = sub.add_parser("summary")
    p_sum.add_argument("--dry-run", action="store_true")
    sub.add_parser("test-alert")
    args = parser.parse_args()

    if args.cmd == "run-once":
        only = set(args.only.split(",")) if args.only else None
        asyncio.run(run_once(args.dry_run, only))
    elif args.cmd == "games":
        asyncio.run(run_games(args.dry_run, args.force))
    elif args.cmd == "summary":
        asyncio.run(summary(args.dry_run))
    else:
        asyncio.run(test_alert())


if __name__ == "__main__":
    main()
