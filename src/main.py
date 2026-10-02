"""PSN India card price scout.

    python -m src.main run-once [--dry-run] [--only seagm,eneba]
    python -m src.main summary [--dry-run]
    python -m src.main test-alert
"""
import argparse
import asyncio
import logging
import sys

import httpx
import structlog

from src import pricing
from src.config import config
from src.db import DB, now_iso
from src.fx import fetch_rates
from src.models import Offer, SourceResult
from src.sources.base import DEFAULT_HEADERS, fetch_all
from src.sources.registry import ALL_SOURCES
from src.telegram_notifier import TelegramNotifier, format_alert, format_broken, format_summary


log = structlog.get_logger()


async def collect(only: set[str] | None) -> tuple[list[SourceResult], list[Offer], dict[str, float]]:
    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=25.0, follow_redirects=True) as client:
        rates = await fetch_rates(client)
        sources = [cls(client) for cls in ALL_SOURCES if not only or cls.name in only]
        results = await fetch_all(sources)
    offers = [o for r in results for o in r.offers]
    return results, pricing.apply(offers, rates, config.FOREIGN_FEE_PCT), rates


def print_table(best: dict[int, list[Offer]], results: list[SourceResult]) -> None:
    for r in results:
        print(f"[{r.status:7}] {r.source:13} {len(r.offers):3} offers {r.error}")
    print()
    for face in config.DENOMINATIONS:
        ranked = best.get(face, [])
        print(f"₹{face:>5}: " + ("out of stock everywhere" if not ranked else ""))
        for o in ranked[:4]:
            print(f"         ₪{o.effective_ils:7.2f} {o.markup_pct:+6.1f}%  {o.store:16} "
                  f"{o.price:g} {o.currency} {o.note}")


async def run_once(dry_run: bool, only: set[str] | None) -> None:
    results, offers, _ = await collect(only)
    best = pricing.best_by_denomination(offers, config.DENOMINATIONS)
    if dry_run:
        print_table(best, results)
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


async def summary(dry_run: bool) -> None:
    results, offers, rates = await collect(None)
    best = pricing.best_by_denomination(offers, config.DENOMINATIONS)
    text = format_summary(best, config.DENOMINATIONS, results, 1000 / rates["INR"])
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
    parser = argparse.ArgumentParser(prog="psn-inr-scout")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run-once")
    p_run.add_argument("--dry-run", action="store_true", help="print prices, no Telegram, no DB")
    p_run.add_argument("--only", help="comma-separated source names")
    p_sum = sub.add_parser("summary")
    p_sum.add_argument("--dry-run", action="store_true")
    sub.add_parser("test-alert")
    args = parser.parse_args()

    if args.cmd == "run-once":
        only = set(args.only.split(",")) if args.only else None
        asyncio.run(run_once(args.dry_run, only))
    elif args.cmd == "summary":
        asyncio.run(summary(args.dry_run))
    else:
        asyncio.run(test_alert())


if __name__ == "__main__":
    main()
