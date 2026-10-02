# PSN India Scout 🎮

Personal bot that tracks **PlayStation Network India (₹) gift card** prices, works out what each
card really costs you in **₪ with an Israeli credit card** (store fees + bank foreign-transaction fee),
and pings Telegram when one is close to face value.

Watches and alerts only. It never logs in or buys anything.

## Sources

| Source | What it gives | Notes |
|---|---|---|
| dlcompare.in | Eneba, Kinguin, GAMESEAL, HRK, K4G, Eldorado | Price **with credit-card fee** + coupon code. India-region only ("Asia" cards dropped). |
| SEAGM | Their own stock, ₹1000–8000 | Usually the cheapest keyshop-style option (~+40%). Checkout fee estimated (`SEAGM_FEE_PCT`). |
| simplygaming.in | Face-value cards | Usually sold out → acts as a **restock watcher**. Indian store; foreign cards may not work. |
| egiftcards.nz | Face value +~5%, NZD | Cheapest in stock (Oct 2026). Small store, 2.8★ Trustpilot (4 reviews) - test with ₹1000 first. |
| Matiex Store | Face value +~10%, USD | Often sold out → restock watcher. Small store, 4★ (4 reviews). |
| Eneba (direct) | Card values dlcompare lacks | Price excludes Eneba's service fee → estimated (`ENEBA_FEE_PCT`). |
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
