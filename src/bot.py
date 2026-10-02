"""Telegram commands. Runs every few minutes (GitHub Actions), reads new messages, replies.

Only approved users get answers: the owner (TELEGRAM_CHAT_ID) approves others with /allow.
Replies use the price snapshot saved by the scans, so no scraping is needed - except
/add and /game with a link, which read that game's PS Store pages live.
"""
import re
from html import escape
from typing import Optional

import json

import httpx
import structlog
from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup

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

BTN_GAMES = "🎮 המשחקים שלי"
BTN_PLUS = "➕ PS Plus"
BTN_CARDS = "💳 הכי זול לטעון"
BTN_CHECK = "🔎 לבדוק / להוסיף משחק"
BTN_ACCOUNTS = "⚙️ החשבונות שלי"
BTN_HELP = "❓ עזרה"
BUTTON_TO_CMD = {BTN_GAMES: "/list", BTN_PLUS: "/plus", BTN_CARDS: "/cards",
                 BTN_CHECK: "/check", BTN_ACCOUNTS: "/accounts", BTN_HELP: "/help"}
MAIN_MENU = ReplyKeyboardMarkup(
    [[BTN_GAMES, BTN_PLUS], [BTN_CARDS, BTN_CHECK], [BTN_ACCOUNTS, BTN_HELP]],
    resize_keyboard=True, is_persistent=True)
# The list behind Telegram's "Menu" button (set once per COMMANDS_VERSION)
COMMANDS = [("start", "תפריט ראשי"), ("game", "איפה הכי זול לקנות משחק"),
            ("plus", "מחירי PS Plus"), ("cards", "הכי זול לטעון כל חשבון"),
            ("list", "המשחקים שלי"), ("add", "להוסיף משחק למעקב"),
            ("accounts", "אילו חשבונות יש לי"), ("help", "עזרה")]
COMMANDS_VERSION = "2"

HELP = """🎮 <b>בוט מחירי פלייסטיישן</b>
אני משווה מחירים בין החשבונות שלך (🇮🇳 הודו, 🇺🇸 ארה"ב, 🇯🇵 יפן) כולל עלות כרטיסי המתנה, ואומר מה לקנות ואיפה.

👇 <b>הכי קל: הכפתורים למטה.</b>
🎮 המשחקים שלי - מחירים + מדריך קנייה לכל משחק
➕ PS Plus - איפה הכי זול ואילו כרטיסים לקנות
💳 הכי זול לטעון - הכרטיס הכי משתלם לכל חשבון
🔎 לבדוק משחק - שולחים קישור מחנות פלייסטיישן
⚙️ החשבונות שלי - אילו חשבונות יש לך

או לכתוב: <code>/game gta 6</code> · <code>/plus extra</code>

📩 התראות מגיעות לבד: מבצע על משחק שלך, מבצע ב-PS Plus, כרטיס הודי בזול. סיכום כל בוקר ב-9.
⏱ תשובות מגיעות תוך דקה-שתיים."""

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
    lines += ["", "👇 לבחור מנוי למדריך קנייה"]
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


def plus_buttons(snap: dict, regions: list[str]) -> InlineKeyboardMarkup:
    row = []
    for tier in ("Essential", "Extra", "Premium"):
        rows = [r for r in (snap.get("plans") or {}).get(f"{tier}:12", []) if r["region"] in regions]
        label = f"{tier} ₪{min(r['ils'] for r in rows):.0f}" if rows else tier
        row.append(Btn(label, callback_data=f"plus:{tier}"))
    return InlineKeyboardMarkup([row])


def accounts_buttons(regions: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        Btn(f"{FLAGS[r]} {'✅' if r in regions else '❌'}", callback_data=f"acct:{r}") for r in REGIONS]])


class Bot:
    def __init__(self, db: DB, notifier: TelegramNotifier, client: httpx.AsyncClient, owner_id: str):
        self.db, self.notifier, self.client, self.owner = db, notifier, client, str(owner_id)

    async def reply(self, chat_id: str, text: str, markup=None) -> None:
        await self.notifier.send_html(text, chat_id=chat_id, reply_markup=markup)

    async def ensure_commands(self) -> None:
        if self.db.get_meta("commands_version") != COMMANDS_VERSION:
            await self.notifier.set_commands(COMMANDS)
            self.db.set_meta("commands_version", COMMANDS_VERSION)

    async def process_inbox(self) -> int:
        await self.ensure_commands()
        offset = int(self.db.get_meta("tg_offset") or 0)
        updates = await self.notifier.get_updates(offset)
        for upd in updates:
            # Advance first, so one bad message can't block the inbox forever
            self.db.set_meta("tg_offset", str(upd.update_id + 1))
            cq = getattr(upd, "callback_query", None)
            msg = upd.message
            try:
                if cq and cq.message:
                    await self.notifier.answer_button(cq.id)
                    await self.handle_button(str(cq.message.chat.id), cq.data or "",
                                             (cq.from_user.first_name if cq.from_user else "") or "")
                elif msg and msg.text:
                    await self.handle(str(msg.chat.id), msg.text.strip(),
                                      (msg.from_user.first_name if msg.from_user else "") or "")
            except Exception as e:
                log.error("bot.command_failed", error=type(e).__name__)
                chat = cq.message.chat.id if cq and cq.message else msg.chat.id if msg else None
                if chat:
                    await self.reply(str(chat), "😵 משהו השתבש. נסה שוב, ואם זה חוזר תגיד למנהל.")
        return len(updates)

    async def _approved(self, chat_id: str, name: str) -> Optional[dict]:
        """The user if approved; otherwise registers them, asks the owner, and returns None."""
        user = self.db.get_user(chat_id)
        if user and user["approved"]:
            return user
        if self.db.add_pending_user(chat_id, name):
            await self.reply(self.owner, f"👤 <b>{escape(name) or 'מישהו'}</b> רוצה להשתמש בבוט.\n"
                                         f"לאשר: /allow {chat_id}")
        await self.reply(chat_id, "👋 היי! ביקשתי אישור מהמנהל של הבוט. אעדכן כשתאושר.")
        return None

    async def handle(self, chat_id: str, text: str, name: str) -> None:
        user = await self._approved(chat_id, name)
        if not user:
            return
        text = BUTTON_TO_CMD.get(text, text)
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = arg.strip()
        is_owner = chat_id == self.owner
        log.info("bot.command", cmd=cmd if cmd.startswith("/") else "text")   # no content/ids: logs are public
        snap = self.db.get_snapshot()
        regions = user["regions"]

        if cmd in ("/start", "/help"):
            await self.reply(chat_id, HELP + (OWNER_HELP if is_owner else ""), MAIN_MENU)
        elif cmd == "/cards":
            await self.reply(chat_id, cards_text(snap, regions))
        elif cmd == "/plus":
            tier = TIER_WORDS.get(arg.split()[0].lower()) if arg else None
            months = next((int(w) for w in arg.split() if w.isdigit() and int(w) in (1, 3, 12)), 12)
            if tier:
                await self.reply(chat_id, self.plus_guide(snap, tier, months, regions))
            else:
                await self.reply(chat_id, plus_overview(snap, regions), plus_buttons(snap, regions))
        elif cmd == "/game":
            await self.cmd_game(chat_id, arg, snap, regions)
        elif cmd == "/add":
            await self.cmd_add(chat_id, arg, snap, regions)
        elif cmd == "/check":
            await self.reply(chat_id, "🔎 שלח לי קישור למשחק מחנות פלייסטיישן (store.playstation.com).\n"
                                      "באפליקציה של פלייסטיישן: נכנסים למשחק ← שיתוף ← העתקת קישור.\n\n"
                                      "אגיד כמה הוא עולה בכל חשבון ואילו כרטיסים לקנות, ותוכל להוסיף אותו למעקב.")
        elif cmd == "/list":
            await self.cmd_list(chat_id, snap, regions)
        elif cmd == "/remove":
            rows = self.db.watch_rows(chat_id)
            if arg.isdigit() and 1 <= int(arg) <= len(rows):
                title = self.db.remove_watch_id(chat_id, rows[int(arg) - 1]["id"])
                await self.reply(chat_id, f"🗑 הוסר: {escape(title or '')}")
            else:
                await self.reply(chat_id, "איזה מספר? ראה /list")
        elif cmd == "/accounts":
            chosen = parse_regions(arg)
            if chosen:
                self.db.set_regions(chat_id, chosen)
                regions = chosen
            await self.reply(chat_id, "⚙️ <b>אילו חשבונות יש לך?</b> לוחצים כדי להדליק/לכבות:",
                             accounts_buttons(regions))
        elif is_owner and cmd == "/allow" and arg:
            if self.db.approve_user(arg):
                await self.reply(arg, "🎉 אושרת!\n\n" + HELP, MAIN_MENU)
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
            await self.reply(chat_id, "לא הבנתי 🙂 אפשר להשתמש בכפתורים למטה.", MAIN_MENU)

    async def handle_button(self, chat_id: str, data: str, name: str) -> None:
        user = await self._approved(chat_id, name)
        if not user:
            return
        kind, _, value = data.partition(":")
        log.info("bot.button", kind=kind)
        snap = self.db.get_snapshot()
        regions = user["regions"]
        if kind == "plus":
            await self.reply(chat_id, self.plus_guide(snap, value, 12, regions))
        elif kind == "acct" and value in REGIONS:
            new = [r for r in REGIONS if (r in regions) != (r == value)]
            if not new:
                await self.reply(chat_id, "צריך לפחות חשבון אחד 🙂")
                return
            self.db.set_regions(chat_id, new)
            await self.reply(chat_id, "✅ עודכן: " + " ".join(FLAGS[r] for r in new), accounts_buttons(new))
        elif kind == "g" and value.isdigit():
            row = next((w for w in self.db.watch_rows(chat_id) if w["id"] == int(value)), None)
            if not row:
                await self.reply(chat_id, "המשחק כבר לא ברשימה שלך.")
                return
            g = (snap.get("games") or {}).get(row["key"])
            if not g:
                c = await self._fetch(row["line"], snap)
                g = snap_mod.game_entry(c) if c else None
            if not g:
                await self.reply(chat_id, "😕 עדיין אין לי מחירים למשחק הזה. נסה שוב בעוד כמה שעות.")
                return
            await self.reply(chat_id, buy_guide(snap, g["title"], g["edition"], g["rows"], regions))
        elif kind == "rm" and value.isdigit():
            title = self.db.remove_watch_id(chat_id, int(value))
            await self.reply(chat_id, f"🗑 הוסר: {escape(title)}" if title else "כבר הוסר.")
        elif kind == "add":
            pending = json.loads(self.db.get_meta(f"pending_add:{chat_id}") or "{}")
            if not pending:
                await self.reply(chat_id, "שלח שוב את הקישור למשחק ואז לחץ להוסיף.")
                return
            added = self.db.add_watch(chat_id, pending["line"], pending["title"], pending["key"])
            await self.reply(chat_id, f"✅ {escape(pending['title'])} נוסף למעקב! אודיע כשיהיה מבצע."
                             if added else "כבר במעקב 👍")
        elif kind == "check":
            await self.handle(chat_id, "/check", name)

    def plus_guide(self, snap: dict, tier: str, months: int, regions: list[str]) -> str:
        rows = (snap.get("plans") or {}).get(f"{tier}:{months}", [])
        if not rows:
            return "⏳ אין עדיין מחירי PS Plus. נסה שוב בעוד כמה שעות."
        rows = [dict(r, url=f"https://www.playstation.com/{games_mod.LOCALES[r['region']]}/ps-plus/")
                for r in rows]
        text = buy_guide(snap, f"PS Plus {tier} - {months} חודשים", "", rows, regions)
        mine = [r for r in rows if r["region"] in regions]
        if mine and min(mine, key=lambda r: r["ils"])["region"] == "JP":
            text += ("\n\n💡 כדי שגם החשבונות האחרים בקונסולה ייהנו: בחשבון היפני ב-PS5 - "
                     "Settings ← Users and Accounts ← Other ← Console Sharing and Offline Play ← Enable")
        return text

    async def cmd_list(self, chat_id: str, snap: dict, regions: list[str]) -> None:
        rows = self.db.watch_rows(chat_id)
        add_row = [Btn("🔎 להוסיף משחק", callback_data="check")]
        if not rows:
            await self.reply(chat_id, "הרשימה שלך ריקה.", InlineKeyboardMarkup([add_row]))
            return
        buttons = []
        for w in rows:
            g = (snap.get("games") or {}).get(w["key"])
            mine = sorted((r for r in (g or {}).get("rows", []) if r["region"] in regions),
                          key=lambda r: r["ils"])
            price = f" {FLAGS[mine[0]['region']]} ₪{mine[0]['ils']:.0f}" if mine else ""
            label = (w["title"] or "משחק")[:28] + price
            buttons.append([Btn(label, callback_data=f"g:{w['id']}"), Btn("🗑", callback_data=f"rm:{w['id']}")])
        buttons.append(add_row)
        await self.reply(chat_id, "🎮 <b>המשחקים שלך</b> - לחיצה על משחק = מדריך קנייה",
                         InlineKeyboardMarkup(buttons))

    async def cmd_game(self, chat_id: str, arg: str, snap: dict, regions: list[str]) -> None:
        if not arg:
            await self.reply(chat_id, "איזה משחק? למשל: /game gta 6\nאו שלח קישור מ-store.playstation.com")
            return
        link = STORE_LINK_RE.search(arg)
        markup = None
        if link:
            c = await self._fetch(link.group(0), snap)
            if not c:
                await self.reply(chat_id, "😕 לא הצלחתי לקרוא את המחירים מהקישור הזה.")
                return
            g = snap_mod.game_entry(c)
            if link.group(0) not in [w["line"] for w in self.db.watch_rows(chat_id)]:
                self.db.set_meta(f"pending_add:{chat_id}", json.dumps(
                    {"line": link.group(0), "title": c.title, "key": c.concept_id}, ensure_ascii=False))
                markup = InlineKeyboardMarkup([[Btn("➕ להוסיף למעקב", callback_data="add")]])
        else:
            g = find_game(snap, arg)
            if not g:
                await self.reply(chat_id, "לא מצאתי את המשחק ברשימות המעקב 🤔\n"
                                          "שלח קישור מ-store.playstation.com ואבדוק אותו.")
                return
        await self.reply(chat_id, buy_guide(snap, g["title"], g["edition"], g["rows"], regions), markup)

    async def cmd_add(self, chat_id: str, arg: str, snap: dict, regions: list[str]) -> None:
        link = STORE_LINK_RE.search(arg)
        if not link:
            await self.handle(chat_id, "/check", "")
            return
        line = link.group(0)
        c = await self._fetch(line, snap)
        if not c:
            await self.reply(chat_id, "😕 לא הצלחתי לקרוא את הקישור הזה. בדוק שהוא נפתח בדפדפן.")
            return
        added = self.db.add_watch(chat_id, line, c.title, c.concept_id)
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
