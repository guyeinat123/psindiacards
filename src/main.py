"""PSN wallet card + game + PS Plus price bot (India / US / Japan accounts), for several users.

    python -m src.main tick                       # what GitHub runs every 5 min: inbox + whatever is due
    python -m src.main run-once [--dry-run] [--only seagm,eneba]   # card scan now
    python -m src.main games [--dry-run]          # watched games + PS Plus now
    python -m src.main summary [--dry-run]        # morning summary now
    python -m src.main test-alert
"""
import argparse
import asyncio
import logging
import sys
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import structlog

from src import games as games_mod
from src import pricing, psplus
from src import snapshot as snap_mod
from src.bot import Bot
from src.config import config
from src.db import DB, now_iso
from src.fx import fetch_rates
from src.models import REGIONS, Offer, SourceResult
from src.sources.base import DEFAULT_HEADERS, fetch_all
from src.sources.registry import ALL_SOURCES
from src.telegram_notifier import (TelegramNotifier, format_alert, format_broken,
                                   format_game_alert, format_psplus_alert, format_summary)


log = structlog.get_logger()

PlanMap = dict[tuple[str, int], list[psplus.PlanPrice]]


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=25.0, follow_redirects=True)


# ---- collecting ------------------------------------------------------------------

async def collect(client: httpx.AsyncClient, only: Optional[set[str]] = None
                  ) -> tuple[list[SourceResult], list[Offer], dict[str, float]]:
    rates = await fetch_rates(client)
    sources = [cls(client) for cls in ALL_SOURCES if not only or cls.name in only]
    results = await fetch_all(sources)
    offers = [o for r in results for o in r.offers]
    return results, pricing.apply(offers, rates, config.FOREIGN_FEE_PCT), rates


def best_cards_by_region(offers: list[Offer]) -> dict[str, Optional[Offer]]:
    return {region: pricing.best_rate(offers, region) for region in REGIONS}


async def check_games(client: httpx.AsyncClient, lines: list[str],
                      wallet: dict[str, float]) -> dict[str, games_mod.Comparison]:
    """line -> comparison, for every watched line that could be priced."""
    sem = asyncio.Semaphore(3)

    async def one(line: str):
        async with sem:
            try:
                return line, await games_mod.fetch_game(client, line, wallet)
            except Exception as e:
                log.error("game.failed", error=f"{type(e).__name__}: {e}")
                return line, None
    found = await asyncio.gather(*(one(l) for l in lines))
    return {line: c for line, c in found if c and c.rows}


async def check_psplus(client: httpx.AsyncClient, wallet: dict[str, float]) -> PlanMap:
    try:
        return await psplus.fetch_all(client, wallet)
    except Exception as e:
        log.error("psplus.failed", error=f"{type(e).__name__}: {e}")
        return {}


# ---- per-user filtering ------------------------------------------------------------

def for_regions(c: games_mod.Comparison, regions: list[str]) -> Optional[games_mod.Comparison]:
    rows = [r for r in c.rows if r.region in regions]
    return replace(c, rows=rows) if rows else None


def plans_for(plans: PlanMap, regions: list[str]) -> PlanMap:
    out = {k: [p for p in rows if p.region in regions] for k, rows in plans.items()}
    return {k: v for k, v in out.items() if v}


# ---- the jobs --------------------------------------------------------------------

def seed_owner(db: DB) -> None:
    """Owner is always approved; games.txt seeds the owner's watchlist once (Telegram /add after)."""
    db.ensure_owner(config.TELEGRAM_CHAT_ID)
    if config.TELEGRAM_CHAT_ID and not db.get_meta("games_txt_seeded"):
        for line in games_mod.read_watchlist(config.GAMES_FILE):
            db.add_watch(config.TELEGRAM_CHAT_ID, line)
        db.set_meta("games_txt_seeded", now_iso())


async def scan_cards(db: DB, notifier: TelegramNotifier, client: httpx.AsyncClient) -> None:
    results, offers, rates = await collect(client)
    db.save_daily_lows(offers)
    db.update_snapshot(cards=snap_mod.cards_part(offers), rates=rates, cards_at=now_iso())
    india_users = [u for u in db.approved_users() if "IN" in u["regions"]]
    best = pricing.best_by_denomination(offers, config.DENOMINATIONS, "IN")
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
            for u in india_users:
                await notifier.send_html(text, chat_id=u["chat_id"])
            db.record_alert(top)
            log.info("alert.sent", face=face, store=top.store, ils=top.effective_ils)
    for r in results:
        if db.update_health(r, config.BROKEN_AFTER_FAILURES):
            await notifier.send_html(format_broken(r))      # owner only


async def scan_games(db: DB, notifier: TelegramNotifier, client: httpx.AsyncClient) -> None:
    snap = db.get_snapshot()
    wallet = snap_mod.wallet_costs(snap)
    if not wallet:
        log.info("games.no_card_prices_yet")
        return
    watches = db.watches()
    lines = list(dict.fromkeys(line for _, line, _ in watches))
    found = await check_games(client, lines, wallet)
    plans = await check_psplus(client, wallet)
    users = {u["chat_id"]: u for u in db.approved_users()}
    best_cards = {r: _offer_from_snap(snap, r) for r in REGIONS}

    for line, c in found.items():
        db.set_watch_title(line, c.title, c.concept_id)
        baseline = db.game_baseline(c.concept_id)
        alert, new_baseline = pricing.game_decision(
            c.best.effective_ils, baseline, config.MIN_GAME_DROP_PCT)
        if alert:
            for chat_id in {cid for cid, l, _ in watches if l == line and cid in users}:
                mine = for_regions(c, users[chat_id]["regions"])
                if mine:
                    await notifier.send_html(format_game_alert(mine, baseline, best_cards), chat_id=chat_id)
            log.info("game.alert", game=c.title, region=c.best.region, ils=c.best.effective_ils)
        db.save_game(c.concept_id, c.title, c.best.region, c.best.effective_ils, new_baseline)

    for (tier, months), rows in plans.items():
        if months != 12:
            continue
        key = f"psplus:{tier}:12"
        baseline = db.game_baseline(key)
        alert, new_baseline = pricing.game_decision(
            rows[0].effective_ils, baseline, config.MIN_GAME_DROP_PCT)
        if alert:
            for u in users.values():
                mine = [p for p in rows if p.region in u["regions"]]
                if mine:
                    await notifier.send_html(format_psplus_alert(mine, baseline, best_cards),
                                             chat_id=u["chat_id"])
            log.info("psplus.alert", tier=tier, region=rows[0].region, ils=rows[0].effective_ils)
        db.save_game(key, f"PS Plus {tier} 12m", rows[0].region, rows[0].effective_ils, new_baseline)

    db.update_snapshot(
        games={c.concept_id: snap_mod.game_entry(c) for c in found.values()},
        plans=snap_mod.plans_part(plans) if plans else snap.get("plans", {}),
        games_at=now_iso(),
    )


def _offer_from_snap(snap: dict, region: str) -> Optional[Offer]:
    """The snapshot's best card as an Offer, for the alert formatters."""
    c = snap_mod.best_card(snap, region)
    if not c:
        return None
    return Offer("snapshot", c["store"], c["face"], 0, REGIONS[region], c["url"], note=c.get("note", ""),
                 region=region, effective_ils=c["ils"], markup_pct=c["markup"])


async def send_summaries(db: DB, notifier: TelegramNotifier, client: httpx.AsyncClient,
                         dry_run: bool = False) -> None:
    results, offers, rates = await collect(client)
    wallet = games_mod.wallet_costs(best_cards_by_region(offers), rates)
    watches = db.watches() if db else []
    lines = list(dict.fromkeys(line for _, line, _ in watches)) or games_mod.read_watchlist(config.GAMES_FILE)
    found = await check_games(client, lines, wallet)
    plans = await check_psplus(client, wallet)
    best = pricing.best_by_denomination(offers, config.DENOMINATIONS, "IN")
    users = db.approved_users() if db else [{"chat_id": config.TELEGRAM_CHAT_ID, "regions": list(REGIONS)}]
    for u in users:
        regions = u["regions"]
        mine = [line for cid, line, _ in watches if cid == u["chat_id"]] if watches else lines
        user_games = [g for g in (for_regions(found[l], regions) for l in mine if l in found) if g]
        text = format_summary(
            best if "IN" in regions else {}, config.DENOMINATIONS if "IN" in regions else [],
            results, 1000 / rates["INR"],
            {r: o for r, o in best_cards_by_region(offers).items() if r in regions},
            user_games, plans_for(plans, regions))
        if dry_run:
            print(text)
            return
        await notifier.send_html(text, chat_id=u["chat_id"])


def due(db: DB, key: str, every_minutes: float) -> bool:
    """True if `key` last ran at least every_minutes ago (2 min slack for scheduler jitter)."""
    last = db.get_meta(key)
    if not last:
        return True
    elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
    return elapsed.total_seconds() >= (every_minutes - 2) * 60


def summary_due(db: DB) -> bool:
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    return now.hour >= config.SUMMARY_HOUR and db.get_meta("summary_day") != now.date().isoformat()


async def tick() -> None:
    """One GitHub Actions run: answer messages, then run whatever job is due."""
    db = DB(config.DATABASE_PATH)
    try:
        seed_owner(db)
        notifier = TelegramNotifier()
        async with new_client() as client:
            bot = Bot(db, notifier, client, config.TELEGRAM_CHAT_ID)
            handled = await bot.process_inbox()
            db.conn.commit()
            if handled:
                log.info("inbox.handled", count=handled)
            if due(db, "cards_at", 30) or not db.get_snapshot().get("cards"):
                await scan_cards(db, notifier, client)
                db.set_meta("cards_at", now_iso())
                db.conn.commit()
            if due(db, "games_at", config.GAMES_EVERY_HOURS * 60):
                await scan_games(db, notifier, client)
                db.set_meta("games_at", now_iso())
                db.conn.commit()
            if summary_due(db):
                await send_summaries(db, notifier, client)
                db.set_meta("summary_day", datetime.now(ZoneInfo(config.TIMEZONE)).date().isoformat())
            # Messages that arrived during the scans get answered now rather than in 5 minutes
            await bot.process_inbox()
    finally:
        db.close()


# ---- manual commands (local testing) -------------------------------------------

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


async def run_once(dry_run: bool, only: Optional[set[str]]) -> None:
    if dry_run:
        async with new_client() as client:
            results, offers, _ = await collect(client, only)
        print_table(pricing.best_by_denomination(offers, config.DENOMINATIONS, "IN"),
                    results, best_cards_by_region(offers))
        return
    db = DB(config.DATABASE_PATH)
    try:
        seed_owner(db)
        async with new_client() as client:
            await scan_cards(db, TelegramNotifier(), client)
        db.set_meta("cards_at", now_iso())
    finally:
        db.close()


async def run_games(dry_run: bool) -> None:
    if dry_run:
        async with new_client() as client:
            _, offers, rates = await collect(client)
            wallet = games_mod.wallet_costs(best_cards_by_region(offers), rates)
            found = await check_games(client, games_mod.read_watchlist(config.GAMES_FILE), wallet)
            plans = await check_psplus(client, wallet)
        for c in found.values():
            print(f"\n{c.title} [{c.edition_name}]")
            for r in c.rows:
                print(f"   {r.region} ₪{r.effective_ils:8.2f}  {r.edition.price:g} {r.edition.currency}"
                      + (f" (was {r.edition.base_price:g})" if r.edition.price < r.edition.base_price else ""))
        for (tier, months), rows in sorted(plans.items()):
            print(f"PS Plus {tier:9} {months:2}m: " + "  ".join(
                f"{p.region} ₪{p.effective_ils:.0f}" + ("*" if p.on_sale else "") for p in rows))
        return
    db = DB(config.DATABASE_PATH)
    try:
        seed_owner(db)
        async with new_client() as client:
            await scan_games(db, TelegramNotifier(), client)
        db.set_meta("games_at", now_iso())
    finally:
        db.close()


async def summary(dry_run: bool) -> None:
    db = None if dry_run else DB(config.DATABASE_PATH)
    try:
        if db:
            seed_owner(db)
        async with new_client() as client:
            await send_summaries(db, None if dry_run else TelegramNotifier(), client, dry_run)
    finally:
        if db:
            db.close()


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
    sub.add_parser("tick")
    p_run = sub.add_parser("run-once")
    p_run.add_argument("--dry-run", action="store_true", help="print prices, no Telegram, no DB")
    p_run.add_argument("--only", help="comma-separated source names")
    p_games = sub.add_parser("games")
    p_games.add_argument("--dry-run", action="store_true")
    p_sum = sub.add_parser("summary")
    p_sum.add_argument("--dry-run", action="store_true")
    sub.add_parser("test-alert")
    args = parser.parse_args()

    if args.cmd == "tick":
        asyncio.run(tick())
    elif args.cmd == "run-once":
        asyncio.run(run_once(args.dry_run, set(args.only.split(",")) if args.only else None))
    elif args.cmd == "games":
        asyncio.run(run_games(args.dry_run))
    elif args.cmd == "summary":
        asyncio.run(summary(args.dry_run))
    else:
        asyncio.run(test_alert())


if __name__ == "__main__":
    main()
