# PSN Scout 🎮

Personal bot for buying PlayStation games as cheaply as possible across **India, US and Japan** accounts.

1. Tracks **PSN wallet gift card** prices for all three regions and works out what each card really
   costs in **₪ with an Israeli credit card** (store fees + bank foreign-transaction fee).
2. Pings Telegram when an **India** card is close to face value (deal / restock).
3. Compares **PS Plus** (all tiers, 1/3/12 months) across the three stores and alerts when a
   12-month plan's cheapest real price drops ≥10% (a sale).
4. For the games in **`games.txt`**, compares the price on each store × the real cost of that
   region's wallet, and alerts when the cheapest option drops ≥10% (a sale).

## Watching games

Edit `games.txt` on GitHub (open the file → ✏️ → paste a PS Store link on its own line → Commit).
Any region's link works, concept or product. Checked every 3 hours.
The comparison uses the Standard edition when there is one; PS Plus-only prices are ignored.
Note: Japanese-store versions may not include English - check the store page before buying.

Watches and alerts only. It never logs in or buys anything.

## Sources

| Source | What it gives | Notes |
|---|---|---|
| dlcompare (.in + .com) | India + Japan cards from Eneba, Kinguin, GAMESEAL, HRK, K4G, Eldorado | Price **with credit-card fee** + coupon code. India-region only ("Asia" cards dropped). |
| SEAGM | India ₹1000–8000 + Japan ¥1100–15000 | Usually the cheapest keyshop-style option (~+40%). Checkout fee estimated (`SEAGM_FEE_PCT`). |
| simplygaming.in | Face-value cards | Usually sold out → acts as a **restock watcher**. Indian store; foreign cards may not work. |
| egiftcards.nz | Face value +~5%, NZD | Cheapest in stock (Oct 2026). Small store, 2.8★ Trustpilot (4 reviews) - test with ₹1000 first. |
| Matiex Store | India ~+10% (often sold out), **US cards ~5% below face** | Small store, 4★ (4 reviews). |
| Eneba (direct) | India, US and Japan listings | Price excludes Eneba's service fee → estimated (`ENEBA_FEE_PCT`). |
| Amazon.in | Face-value cards | Amazon blocks scraping, so this goes through the **Keepa API** (paid). Off unless `KEEPA_API_KEY` + `AMAZON_ASINS` set. |

Sites that sit behind a bot check (gg.deals, G2A, Gamivo, Kinguin direct, MTCGame, Play-Asia) are
deliberately not scraped. When a source starts returning a block page, it's reported as 🚫 and skipped.

## How alerts work

- `markup` = how much more than the card's face value you pay, after fees, in ₪.
  Typical today: keyshops +40-65%, face-value stores +2.5% (just your bank fee).
- Alert when the cheapest in-stock card of a value is ≤ `MAX_MARKUP_PCT` (default 15%).
- One alert per deal. Another only if it gets ≥1% cheaper, or after the deal disappears and comes back (restock).
- Daily summary at 09:00: cheapest option per card value + which sources are healthy.
- A source failing 3 runs in a row → one "source broken" message.

## Local use

```bash
uv venv --python 3.12 .venv && uv pip install -r requirements.txt
cp .env.example .env        # fill TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
.venv/bin/python -m src.main run-once --dry-run     # print the price table, nothing sent
.venv/bin/python -m src.main games --dry-run       # game price comparison
.venv/bin/python -m src.main summary --dry-run
.venv/bin/python -m src.main test-alert             # check Telegram works
.venv/bin/python -m pytest
```

## Deploy (GitHub Actions, free)

1. Push to a **private** GitHub repo.
2. Settings → Secrets and variables → Actions:
   - Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optional `KEEPA_API_KEY`)
   - Variables (optional): `MAX_MARKUP_PCT`, `FOREIGN_FEE_PCT`, `AMAZON_ASINS`
3. Actions tab → "Scan PSN India prices" → Run workflow, to test it.

`scan.yml` runs every 30 min; state is kept in the Actions cache (not committed).
`summary.yml` runs daily.

## Fixing a broken source

Each parser has a test against a saved copy of the real page in `tests/fixtures/`.
When a site changes layout: save the new page over the fixture, run pytest, fix the parser.
