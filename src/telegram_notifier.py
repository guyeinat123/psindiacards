"""Format and send price alerts to Telegram (HTML parse mode)."""
from html import escape
from typing import Optional

import structlog
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from src.config import config
from src.games import Comparison
from src.models import FLAGS, Offer, SourceResult


log = structlog.get_logger()

STATUS_ICON = {"ok": "✅", "blocked": "🚫", "error": "❌", "skipped": "⏭"}


def _money(o: Offer) -> str:
    return f"₪{o.effective_ils:.2f} ({o.markup_pct:+.0f}%)"


def format_alert(face: int, ranked: list[Offer], lowest_30d: Optional[float]) -> str:
    best = ranked[0]
    lines = [
        f"🎮 <b>PSN India ₹{face:,}</b> - דיל!",
        "",
        f"💰 <b>{_money(best)}</b> כולל עמלות והמרה",
        f"🏪 {escape(best.store)}" + (f" · {escape(best.note)}" if best.note else ""),
    ]
    if lowest_30d:
        lines.append(f"📉 הכי זול ב-30 יום: ₪{lowest_30d:.2f}")
    lines += ["", f'🔗 <a href="{escape(best.url)}">לקנייה</a>']
    others = [o for o in ranked[1:4] if o.store != best.store]
    if others:
        lines.append("")
        lines.append("עוד: " + " · ".join(f"{escape(o.store)} {_money(o)}" for o in others))
    return "\n".join(lines)


SYMBOL = {"INR": "₹", "USD": "$", "JPY": "¥"}


def _wallet_money(amount: float, currency: str) -> str:
    sym = SYMBOL.get(currency, currency + " ")
    return f"{sym}{amount:,.2f}" if currency == "USD" else f"{sym}{amount:,.0f}"


def format_wallets(best_cards: dict[str, Optional[Offer]]) -> list[str]:
    """One line per account: cheapest way to fund it right now."""
    lines = ["💳 <b>הכי זול לטעון כל חשבון</b> (% = מעל/מתחת לערך הכרטיס, כולל עמלות):"]
    for region, o in best_cards.items():
        if o is None:
            lines.append(f"{FLAGS[region]} אין כרטיס במלאי")
            continue
        face = _wallet_money(o.face, o.face_currency)
        lines.append(f'{FLAGS[region]} <b>{o.markup_pct:+.0f}%</b> - '
                     f'<a href="{escape(o.url)}">{escape(o.store)}</a> כרטיס {face}')
    return lines


def _game_rows(c: Comparison) -> list[str]:
    rows = []
    for i, r in enumerate(c.rows):
        ed = r.edition
        sale = f" (במקום {_wallet_money(ed.base_price, ed.currency)})" if ed.price < ed.base_price else ""
        star = " ⭐ הכי זול" if i == 0 else ""
        rows.append(f'{FLAGS[r.region]} ₪{r.effective_ils:.0f} - '
                    f'<a href="{escape(r.url)}">{_wallet_money(ed.price, ed.currency)}</a>{sale}{star}')
    return rows


def format_game_alert(c: Comparison, old_ils: float, best_cards: dict[str, Optional[Offer]]) -> str:
    best = c.best
    card = best_cards.get(best.region)
    lines = [
        f"🎮 <b>{escape(c.title)}</b> - ירד ל-₪{best.effective_ils:.0f} (היה ₪{old_ils:.0f})",
        f"<i>{escape(c.edition_name)}, מחיר אמיתי כולל עלות כרטיס</i>",
        "",
        *_game_rows(c),
    ]
    if card:
        lines += ["", f'💳 לטעינה: <a href="{escape(card.url)}">{escape(card.store)}</a> '
                      f'({card.markup_pct:+.0f}%)']
    return "\n".join(lines)


def format_summary(best: dict[int, list[Offer]], denominations: list[int],
                   results: list[SourceResult], face_ils_per_1000: float,
                   best_cards: Optional[dict[str, Optional[Offer]]] = None,
                   games: Optional[list[Comparison]] = None) -> str:
    lines = []
    if best_cards:
        lines += format_wallets(best_cards) + [""]
    if games:
        lines.append("🎮 <b>המשחקים שלך - איפה הכי זול</b>")
        for c in games:
            b = c.best
            others = " · ".join(f"{FLAGS[r.region]} ₪{r.effective_ils:.0f}" for r in c.rows[1:])
            lines.append(f'{FLAGS[b.region]} <b>₪{b.effective_ils:.0f}</b> '
                         f'<a href="{escape(b.url)}">{escape(c.title)}</a>'
                         + (f" ({others})" if others else ""))
        lines.append("")
    lines += [
        "📊 <b>PSN India - המחיר הכי זול לכל כרטיס</b>",
        f"<i>(₹1,000 = ₪{face_ils_per_1000:.2f} לפי שער היום, % = מעל ערך הכרטיס)</i>",
        "",
    ]
    for face in denominations:
        ranked = best.get(face)
        if not ranked:
            lines.append(f"₹{face:,}: אין במלאי")
            continue
        o = ranked[0]
        lines.append(f'₹{face:,}: <b>{_money(o)}</b> <a href="{escape(o.url)}">{escape(o.store)}</a>')
    lines.append("")
    lines.append(" ".join(f"{STATUS_ICON.get(r.status, '?')} {r.source}" for r in results))
    return "\n".join(lines)


def format_broken(result: SourceResult) -> str:
    return (f"⚠️ המקור <b>{escape(result.source)}</b> נכשל כמה ריצות ברצף "
            f"({escape(result.status)}: {escape(result.error[:200])}). כדאי לבדוק את הסקרייפר.")


class TelegramNotifier:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        if not self.token or not self.chat_id:
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        self._bot = Bot(token=self.token)

    async def send_html(self, text: str) -> Optional[str]:
        """Returns the Telegram message_id on success, None on failure."""
        try:
            msg = await self._bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return str(msg.message_id)
        except TelegramError as e:
            log.error("telegram.send_failed", error=str(e))
            return None
