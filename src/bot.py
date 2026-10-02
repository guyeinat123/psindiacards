"""Telegram commands. Runs every few minutes (GitHub Actions), reads new messages, replies.

Only approved users get answers: the owner (TELEGRAM_CHAT_ID) approves others with /allow.
Replies use the price snapshot saved by the scans, so no scraping is needed - except
/add and /game with a link, which read that game's PS Store pages live.
"""
import re
from html import escape
from typing import Optional

import httpx
import structlog

from src import games as games_mod
from src import snapshot as snap_mod
from src.combos import cheapest_cover
from src.db import DB
from src.models import FLAGS, REGIONS
from src.telegram_notifier import SYMBOL, TelegramNotifier, _wallet_money


log = structlog.get_logger()

REGION_WORDS = {
    "in": "IN", "india": "IN", "הודו": "IN", "הודי": "IN",
    "us": "US", "usa": "US", "america": "US", "ארהב": "US", 'ארה"ב': "US", "אמריקה": "US",
    "jp": "JP", "japan": "JP", "יפן": "JP", "יפני": "JP",
}
REGION_NAMES = {"IN": "הודי", "US": "אמריקאי", "JP": "יפני"}
TIER_WORDS = {"essential": "Essential", "extra": "Extra", "premium": "Premium", "deluxe": "Premium",
              "אסנשיאל": "Essential", "אקסטרה": "Extra", "פרימיום": "Premium"}
STORE_LINK_RE = re.compile(r"https?://store\.playstation\.com/\S*/(?:concept|product)/\S+")
REDEEM_HINT = "↪️ הפעלת קוד בחשבון: PlayStation Store ← ⋯ ← Redeem Code"

HELP = """🎮 <b>בוט מחירי פלייסטיישן</b>
אני משווה מחירים בין החשבונות שלך (🇮🇳 הודו, 🇺🇸 ארה"ב, 🇯🇵 יפן) כולל עלות כרטיסי המתנה, ואומר מה לקנות ואיפה.

<b>פקודות:</b>
/game gta 6 - איפה הכי זול + אילו כרטיסים לקנות (שם של משחק במעקב, או קישור מחנות פלייסטיישן)
/plus - מחירי PS Plus ל-12 חודשים
/plus extra - מדריך קנייה ל-PS Plus Extra (גם essential / premium)
/cards - הכי זול לטעון כל חשבון עכשיו
/add קישור - להוסיף משחק למעקב (קישור מ-store.playstation.com)
/list - המשחקים שלך במעקב
/remove 2 - להסיר משחק מספר 2 מהרשימה
/accounts in jp - אילו חשבונות יש לך (ברירת מחדל: כל השלושה)

📩 התראות מגיעות לבד: מבצע על משחק שלך, מבצע ב-PS Plus, כרטיס הודי בזול. סיכום כל בוקר.
⏱ תשובות מגיעות תוך כמה דקות (הבוט בודק הודעות כל 5 דקות)."""

OWNER_HELP = """

👑 <b>מנהל:</b>
/users - משתמשים
/allow 123 - לאשר משתמש
/kick 123 - להסיר משתמש"""


def _rows_line(rows: list[dict], skip_first: bool = False) -> str:
    return " · ".join(f"{FLAGS[r['region']]} ₪{r['ils']:.0f}" for r in rows[1 if skip_first else 0:])


def buy_guide(snap: dict, title: str, subtitle: str, rows: list[dict], regions: list[str],
              store_url: Optional[str] = None) -> str:
    """The 'how do I buy this cheapest' answer: best account, which cards, total, links."""
    rows = sorted((r for r in rows if r["region"] in regions), key=lambda r: r["ils"])
    if not rows:
        return f"🤷 <b>{escape(title)}</b> לא נמכר באף אחד מהחשבונות שלך ({' '.join(FLAGS[r] for r in regions)})."
    best = rows[0]
    region, price, cur = best["region"], best["price"], best["currency"]
    sale = f" 🔥 במבצע (במקום {_wallet_money(best['base'], cur)})" if best.get("base", price) > price else ""
    lines = [
        f"🎮 <b>{escape(title)}</b>" + (f"\n<i>{escape(subtitle)}</i>" if subtitle else ""),
        "",
        f"⭐ <b>הכי זול: חשבון {REGION_NAMES[region]} {FLAGS[region]} - {_wallet_money(price, cur)}</b>{sale}",
    ]
    if len(rows) > 1:
        lines.append(f"השוואה: {_rows_line(rows)}")
    combo = cheapest_cover(price, snap_mod.card_options(snap, region))
    if combo:
        lines += ["", "💳 <b>כרטיסים לקנות:</b>"]
        for card, n in combo.picks:
            coupon = f" · קוד <code>{escape(card.note.split()[-1])}</code>" if card.note.startswith("coupon") else ""
            lines.append(f'• {n}× {_wallet_money(card.face, REGIONS[region])} - '
                         f'<a href="{escape(card.url)}">{escape(card.store)}</a>{coupon}')
        left = combo.leftover(price)
        left_txt = f" · יישאר בארנק {_wallet_money(left, cur)}" if left > 0.009 else ""
        lines.append(f"<b>סה״כ ≈ ₪{combo.total_ils:.0f}</b>{left_txt}")
    else:
        lines += ["", f"💳 אין כרגע כרטיס {REGION_NAMES[region]} במלאי באף חנות שאני בודק."]
    url = store_url or best.get("url")
    if url:
        lines += ["", f'🛒 <a href="{escape(url)}">לעמוד בחנות</a>']
    lines.append(REDEEM_HINT)
    return "\n".join(lines)


def plus_overview(snap: dict, regions: list[str]) -> str:
    plans = snap.get("plans") or {}
    if not plans:
        return "⏳ אין עדיין מחירי PS Plus. נסה שוב בעוד כמה שעות."
    lines = ["➕ <b>PS Plus ל-12 חודשים</b> (₪ אמיתי כולל עלות כרטיסים)", ""]
    for tier in ("Essential", "Extra", "Premium"):
        rows = [r for r in plans.get(f"{tier}:12", []) if r["region"] in regions]
        if rows:
            rows.sort(key=lambda r: r["ils"])
            lines.append(f"<b>{tier}</b>: {_rows_line(rows)}")
    lines += ["", "למדריך קנייה: /plus essential או /plus extra או /plus premium"]
    return "\n".join(lines)


def cards_text(snap: dict, regions: list[str]) -> str:
    if not snap.get("cards"):
        return "⏳ אין עדיין מחירים. נסה שוב בעוד חצי שעה."
    lines = ["💳 <b>הכי זול לטעון כל חשבון</b> (% מעל/מתחת לערך הכרטיס, כולל עמלות)", ""]
    for region in regions:
        cards = sorted(snap["cards"].get(region) or [], key=lambda c: c["markup"])
        if not cards:
            lines.append(f"{FLAGS[region]} אין כרטיס במלאי")
            continue
        lines.append(f"{FLAGS[region]} <b>חשבון {REGION_NAMES[region]}</b>")
        for c in cards[:3]:
            coupon = f" · קוד <code>{escape(c['note'].split()[-1])}</code>" if c.get("note", "").startswith("coupon") else ""
            lines.append(f'  {c["markup"]:+.0f}% - {_wallet_money(c["face"], REGIONS[region])} '
                         f'<a href="{escape(c["url"])}">{escape(c["store"])}</a>{coupon}')
    return "\n".join(lines)


def parse_regions(text: str) -> list[str]:
    out = []
    for word in re.split(r"[\s,]+", text.lower()):
        r = REGION_WORDS.get(word.strip())
        if r and r not in out:
            out.append(r)
    return out


ROMAN = {str(i): r for i, r in enumerate(
    "i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx".split(), 1)}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9א-ת]+", "", s.lower())


def _title_forms(title: str) -> list[str]:
    """'Grand Theft Auto VI' -> ['grandtheftautovi', 'gtavi'] so 'gta 6' matches."""
    words = re.findall(r"[A-Za-z0-9א-ת]+", title)
    initials = "".join(w if w.lower() in ROMAN.values() or w.isdigit() else w[0] for w in words)
    return [_norm(title), _norm(initials)]


def _query_forms(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9א-ת]+", query.lower())
    return list(dict.fromkeys([_norm(query), "".join(ROMAN.get(w, w) for w in words)]))


def find_game(snap: dict, query: str) -> Optional[dict]:
    queries = [q for q in _query_forms(query) if q]
    for g in (snap.get("games") or {}).values():
        forms = _title_forms(g["title"])
        if any(q in f for q in queries for f in forms):
            return g
    return None


class Bot:
    def __init__(self, db: DB, notifier: TelegramNotifier, client: httpx.AsyncClient, owner_id: str):
        self.db, self.notifier, self.client, self.owner = db, notifier, client, str(owner_id)

    async def reply(self, chat_id: str, text: str) -> None:
        await self.notifier.send_html(text, chat_id=chat_id)

    async def process_inbox(self) -> int:
        offset = int(self.db.get_meta("tg_offset") or 0)
        updates = await self.notifier.get_updates(offset)
        for upd in updates:
            # Advance first, so one bad message can't block the inbox forever
            self.db.set_meta("tg_offset", str(upd.update_id + 1))
            msg = upd.message
            if not msg or not msg.text:
                continue
            try:
                await self.handle(str(msg.chat.id), msg.text.strip(),
                                  (msg.from_user.first_name if msg.from_user else "") or "")
            except Exception as e:
                log.error("bot.command_failed", error=type(e).__name__)
                await self.reply(str(msg.chat.id), "😵 משהו השתבש. נסה שוב, ואם זה חוזר תגיד למנהל.")
        return len(updates)

    async def handle(self, chat_id: str, text: str, name: str) -> None:
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = arg.strip()
        user = self.db.get_user(chat_id)
        is_owner = chat_id == self.owner
        log.info("bot.command", cmd=cmd if cmd.startswith("/") else "text")   # no content/ids: logs are public

        if not user or not user["approved"]:
            if self.db.add_pending_user(chat_id, name):
                await self.reply(self.owner, f"👤 <b>{escape(name) or 'מישהו'}</b> רוצה להשתמש בבוט.\n"
                                             f"לאשר: /allow {chat_id}")
            await self.reply(chat_id, "👋 היי! ביקשתי אישור מהמנהל של הבוט. אעדכן כשתאושר.")
            return

        snap = self.db.get_snapshot()
        regions = user["regions"]

        if cmd in ("/start", "/help"):
            await self.reply(chat_id, HELP + (OWNER_HELP if is_owner else ""))
        elif cmd == "/cards":
            await self.reply(chat_id, cards_text(snap, regions))
        elif cmd == "/plus":
            tier = TIER_WORDS.get(arg.split()[0].lower()) if arg else None
            months = next((int(w) for w in arg.split() if w.isdigit() and int(w) in (1, 3, 12)), 12)
            if not tier:
                await self.reply(chat_id, plus_overview(snap, regions))
                return
            rows = (snap.get("plans") or {}).get(f"{tier}:{months}", [])
            urls = {r: f"https://www.playstation.com/{games_mod.LOCALES[r]}/ps-plus/" for r in REGIONS}
            rows = [dict(r, url=urls[r["region"]]) for r in rows]
            text = buy_guide(snap, f"PS Plus {tier} - {months} חודשים", "", rows, regions)
            if "JP" in regions and rows and min(rows, key=lambda r: r["ils"])["region"] == "JP":
                text += ("\n\n💡 כדי שגם החשבונות האחרים בקונסולה ייהנו: בחשבון היפני ב-PS5 - "
                         "Settings ← Users and Accounts ← Other ← Console Sharing and Offline Play ← Enable")
            await self.reply(chat_id, text)
        elif cmd == "/game":
            await self.cmd_game(chat_id, arg, snap, regions)
        elif cmd == "/add":
            await self.cmd_add(chat_id, arg, snap, regions)
        elif cmd == "/list":
            rows = self.db.watches(chat_id)
            if not rows:
                await self.reply(chat_id, "הרשימה ריקה. להוספה: /add ואחריו קישור מחנות פלייסטיישן")
            else:
                await self.reply(chat_id, "📋 <b>במעקב:</b>\n" + "\n".join(
                    f"{i}. {escape(title or line)}" for i, (_, line, title) in enumerate(rows, 1))
                    + "\n\nלהסרה: /remove ומספר")
        elif cmd == "/remove":
            rows = self.db.watches(chat_id)
            if arg.isdigit() and 1 <= int(arg) <= len(rows):
                _, line, title = rows[int(arg) - 1]
                self.db.remove_watch(chat_id, line)
                await self.reply(chat_id, f"🗑 הוסר: {escape(title or line)}")
            else:
                await self.reply(chat_id, "איזה מספר? ראה /list")
        elif cmd == "/accounts":
            chosen = parse_regions(arg)
            if chosen:
                self.db.set_regions(chat_id, chosen)
                await self.reply(chat_id, "✅ החשבונות שלך: " + " ".join(FLAGS[r] for r in chosen))
            else:
                await self.reply(chat_id, "כתוב אילו חשבונות יש לך, למשל: /accounts in jp\n"
                                          "עכשיו: " + " ".join(FLAGS[r] for r in regions))
        elif is_owner and cmd == "/allow" and arg:
            if self.db.approve_user(arg):
                await self.reply(arg, "🎉 אושרת! הנה מה שאני יודע לעשות:\n\n" + HELP)
                await self.reply(chat_id, "✅ אושר")
            else:
                await self.reply(chat_id, "לא מצאתי משתמש כזה. ראה /users")
        elif is_owner and cmd == "/kick" and arg and arg != self.owner:
            self.db.remove_user(arg)
            await self.reply(chat_id, "🗑 הוסר")
        elif is_owner and cmd == "/users":
            await self.reply(chat_id, "👥 <b>משתמשים:</b>\n" + "\n".join(
                f"{'✅' if u['approved'] else '⏳'} {escape(u['name'])} - <code>{u['chat_id']}</code>"
                for u in self.db.all_users()))
        elif STORE_LINK_RE.search(text):
            await self.cmd_game(chat_id, text, snap, regions)
        else:
            await self.reply(chat_id, "לא הבנתי 🙂 הנה מה שאני יודע:\n\n" + HELP)

    async def cmd_game(self, chat_id: str, arg: str, snap: dict, regions: list[str]) -> None:
        if not arg:
            await self.reply(chat_id, "איזה משחק? למשל: /game gta 6\nאו שלח קישור מ-store.playstation.com")
            return
        link = STORE_LINK_RE.search(arg)
        if link:
            c = await self._fetch(link.group(0), snap)
            if not c:
                await self.reply(chat_id, "😕 לא הצלחתי לקרוא את המחירים מהקישור הזה.")
                return
            g = snap_mod.game_entry(c)
        else:
            g = find_game(snap, arg)
            if not g:
                await self.reply(chat_id, "לא מצאתי את המשחק ברשימות המעקב 🤔\n"
                                          "שלח קישור מ-store.playstation.com ואבדוק אותו.")
                return
        await self.reply(chat_id, buy_guide(snap, g["title"], g["edition"], g["rows"], regions))

    async def cmd_add(self, chat_id: str, arg: str, snap: dict, regions: list[str]) -> None:
        link = STORE_LINK_RE.search(arg)
        if not link:
            await self.reply(chat_id, "צריך קישור מחנות פלייסטיישן, למשל:\n"
                                      "/add https://store.playstation.com/en-us/concept/10000730")
            return
        line = link.group(0)
        c = await self._fetch(line, snap)
        if not c:
            await self.reply(chat_id, "😕 לא הצלחתי לקרוא את הקישור הזה. בדוק שהוא נפתח בדפדפן.")
            return
        added = self.db.add_watch(chat_id, line, c.title)
        head = "✅ נוסף למעקב! אודיע כשיהיה מבצע.\n\n" if added else "כבר במעקב 👍\n\n"
        g = snap_mod.game_entry(c)
        await self.reply(chat_id, head + buy_guide(snap, g["title"], g["edition"], g["rows"], regions))

    async def _fetch(self, line: str, snap: dict):
        wallet = snap_mod.wallet_costs(snap)
        if not wallet:
            return None
        try:
            return await games_mod.fetch_game(self.client, line, wallet)
        except Exception as e:
            log.error("bot.fetch_failed", error=type(e).__name__)
            return None
