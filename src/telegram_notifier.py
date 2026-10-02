"""Format and send price alerts to Telegram (HTML parse mode)."""
from html import escape
from typing import Optional

import structlog
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from src.config import config
from src.models import Offer, SourceResult


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


def format_summary(best: dict[int, list[Offer]], denominations: list[int],
                   results: list[SourceResult], face_ils_per_1000: float) -> str:
    lines = [
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
