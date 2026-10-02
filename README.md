# PSN Scout 🎮

A Telegram bot for buying PlayStation games and PS Plus as cheaply as possible across
**India 🇮🇳, US 🇺🇸 and Japan 🇯🇵** accounts, for a few friends.

Every price is turned into **what it really costs in ₪ with an Israeli credit card**: the store
price × what that region's wallet costs to fill (cheapest gift card, store fees, bank
foreign-transaction fee). The bot then says which account to buy on and **exactly which cards
to buy**, with links.

## Using it (Telegram)

| Command | |
|---|---|
| `/game gta 6` | Cheapest account for a watched game + which cards to buy. Or send any PS Store link. |
| `/plus` · `/plus extra` | PS Plus 12-month prices · buying guide for a tier (`essential` / `extra` / `premium`) |
| `/cards` | Cheapest way to fill each account right now |
| `/add <PS Store link>` · `/list` · `/remove 2` | Your watchlist (alerts when a game drops ≥10%) |
| `/accounts in jp` | Which accounts you have (default: all three) |
| `/users` · `/allow <id>` · `/kick <id>` | Owner only |

New people send `/start`; the owner gets a message with `/allow <id>`. Unapproved users get nothing.

Automatic messages: game / PS Plus sales on your accounts, India cards near face value
(deals and restocks), and a summary every morning at 09:00 (Israel time).

## How it runs

One GitHub Actions workflow (`.github/workflows/bot.yml`) answers messages, scans card prices
every 30 min, games + PS Plus every 3 h, and sends the morning summary.

It is started by a free **Cloudflare Worker** (`cloudflare/worker.js`, Cron Trigger every minute):
immediately when a Telegram message is waiting, and every 5 minutes regardless. GitHub's own
`schedule:` in the workflow is only a backup, because GitHub often doesn't run it.
State (users, watchlists, alert history, latest prices) is a small SQLite file kept in the
Actions cache. Replies take about 1-2 minutes (the time for GitHub to start the run).

Logs of a public repo are public, so the bot never logs message text, names or chat ids.

## Price sources

| Source | Cards | Notes |
|---|---|---|
| dlcompare (.in / .com) | India + Japan cards from Eneba, Kinguin, GAMESEAL, HRK, K4G, Eldorado | Prices incl. credit-card fee and the coupon code shown. |
| SEAGM | India + Japan | Reliable, ~+16% for Japan, ~+43% for India. |
| egiftcards.nz | India, ~+8% | Small store (2.8★, few reviews) - try a small card first. |
| Matiex Store | India (often sold out), **US ~5% below face** | Small store (4★, few reviews). |
| simplygaming.in | India at face value | Usually sold out → restock alerts. |
| Eneba | India / US / Japan listings | Price excludes Eneba's fee → estimated (`ENEBA_FEE_PCT`). |
| Amazon.in | | Blocks scraping. Use a free tracker bot (e.g. DealTrackerProBot) for Amazon.in. |
| PlayStation Store / playstation.com | Game and PS Plus prices per region | |

Sites behind a bot check (gg.deals, G2A, Gamivo, Kinguin direct, MTCGame, Play-Asia) are not scraped.

## Setup

1. GitHub repo secrets: `TELEGRAM_BOT_TOKEN` (from @BotFather), `TELEGRAM_CHAT_ID` (the owner).
2. Optional repo variables: `FOREIGN_FEE_PCT` (your card's fee, default 2.5), `MAX_MARKUP_PCT`,
   `MIN_GAME_DROP_PCT`.
3. `games.txt` seeds the owner's watchlist on the very first run; after that use `/add` and `/remove`.

## Local development

```bash
uv venv --python 3.12 .venv && uv pip install -r requirements.txt
cp .env.example .env                                # TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
.venv/bin/python -m src.main run-once --dry-run     # card prices table
.venv/bin/python -m src.main games --dry-run        # games.txt + PS Plus comparison
.venv/bin/python -m src.main summary --dry-run
.venv/bin/python -m pytest
```

When a site changes its layout: save the new page over its file in `tests/fixtures/`,
run pytest, fix the parser.
