import asyncio

import pytest

from src.bot import Bot, buy_guide, find_game, parse_regions
from src.db import DB

JP = 1 / 51.357
SNAP = {
    "cards": {
        "IN": [{"face": 1000, "ils": 34.52, "markup": 8.1, "store": "egiftcards.nz", "url": "https://e", "note": ""},
               {"face": 5000, "ils": 172.59, "markup": 8.1, "store": "egiftcards.nz", "url": "https://e", "note": ""}],
        "US": [{"face": 100, "ils": 294.15, "markup": -4.4, "store": "Matiex Store", "url": "https://m", "note": ""}],
        "JP": [{"face": 5000, "ils": round(5000 * JP * 1.108, 2), "markup": 10.8, "store": "Eneba",
                "url": "https://d", "note": "coupon 3DLC"},
               {"face": 1100, "ils": round(1100 * JP * 1.16, 2), "markup": 16.0, "store": "SEAGM",
                "url": "https://s", "note": ""}],
    },
    "plans": {"Extra:12": [
        {"region": "JP", "price": 11700, "base": 11700, "currency": "JPY", "ils": 252.4},
        {"region": "IN", "price": 8709, "base": 8709, "currency": "INR", "ils": 300.6},
        {"region": "US", "price": 134.99, "base": 134.99, "currency": "USD", "ils": 397.0}]},
    "games": {"10000730": {"key": "10000730", "title": "Grand Theft Auto VI", "edition": "Standard Edition",
                           "rows": [{"region": "IN", "price": 5999, "base": 5999, "currency": "INR",
                                     "ils": 207.1, "url": "https://store/in"},
                                    {"region": "US", "price": 79.99, "base": 79.99, "currency": "USD",
                                     "ils": 235.2, "url": "https://store/us"}]}},
}


class FakeNotifier:
    def __init__(self):
        self.sent, self.markups = [], []

    async def send_html(self, text, chat_id=None, reply_markup=None):
        self.sent.append((chat_id or "owner", text))
        self.markups.append(reply_markup)
        return "1"

    async def set_commands(self, commands):
        self.commands = commands

    async def answer_button(self, callback_id, text=""):
        pass


def make_bot(tmp_path):
    db = DB(str(tmp_path / "b.db"))
    db.ensure_owner("1")
    db.update_snapshot(**SNAP)
    n = FakeNotifier()
    return Bot(db, n, client=None, owner_id="1"), db, n


def test_buy_guide_gta_india_cards_and_total():
    g = SNAP["games"]["10000730"]
    text = buy_guide(SNAP, g["title"], g["edition"], g["rows"], ["IN", "US", "JP"])
    assert "חשבון הודי" in text and "₹5,999" in text
    assert "1× ₹5,000" in text and "1× ₹1,000" in text
    assert "יישאר בארנק ₹1" in text


def test_buy_guide_respects_user_accounts():
    g = SNAP["games"]["10000730"]
    text = buy_guide(SNAP, g["title"], g["edition"], g["rows"], ["US"])
    assert "חשבון אמריקאי" in text and "1× $100.00" in text


def test_buy_guide_coupon_shown():
    rows = SNAP["plans"]["Extra:12"]
    text = buy_guide(SNAP, "PS Plus Extra", "", rows, ["IN", "US", "JP"])
    assert "2× ¥5,000" in text and "2× ¥1,100" in text and "<code>3DLC</code>" in text


def test_find_game_and_regions():
    for q in ("gta 6", "GTA VI", "gta", "grand theft", "Grand Theft Auto 6"):
        assert find_game(SNAP, q)["key"] == "10000730", q
    assert find_game(SNAP, "zelda") is None
    assert parse_regions("in, יפן usa") == ["IN", "JP", "US"]


def test_stranger_needs_approval_then_gets_help(tmp_path):
    bot, db, n = make_bot(tmp_path)
    asyncio.run(bot.handle("2", "/start", "Friend"))
    assert any(cid == "1" and "/allow 2" in t for cid, t in n.sent)        # owner asked
    assert any(cid == "2" and "אישור" in t for cid, t in n.sent)
    n.sent.clear()
    asyncio.run(bot.handle("2", "/cards", "Friend"))                       # still pending
    assert all("₪" not in t for _, t in n.sent)
    asyncio.run(bot.handle("1", "/allow 2", "Owner"))
    assert db.get_user("2")["approved"]
    n.sent.clear()
    asyncio.run(bot.handle("2", "/plus extra", "Friend"))
    reply = n.sent[-1][1]
    assert "חשבון יפני" in reply and "Console Sharing" in reply


def test_friend_cannot_use_owner_commands(tmp_path):
    bot, db, n = make_bot(tmp_path)
    db.add_pending_user("2", "Friend"); db.approve_user("2")
    db.add_pending_user("3", "Stranger")
    asyncio.run(bot.handle("2", "/allow 3", "Friend"))
    assert not db.get_user("3")["approved"]


def test_accounts_and_list(tmp_path):
    bot, db, n = make_bot(tmp_path)
    asyncio.run(bot.handle("1", "/accounts in jp", "Owner"))
    assert db.get_user("1")["regions"] == ["IN", "JP"]
    asyncio.run(bot.handle("1", "/list", "Owner"))
    assert "ריקה" in n.sent[-1][1]
    asyncio.run(bot.handle("1", "/game gta", "Owner"))
    assert "Grand Theft Auto VI" in n.sent[-1][1]


def test_menu_buttons_route_to_commands(tmp_path):
    from src.bot import BTN_CARDS, BTN_PLUS, MAIN_MENU
    bot, db, n = make_bot(tmp_path)
    asyncio.run(bot.handle("1", "/start", "Owner"))
    assert n.markups[-1] is MAIN_MENU
    asyncio.run(bot.handle("1", BTN_CARDS, "Owner"))
    assert "הכי זול לטעון" in n.sent[-1][1] and "Eneba" in n.sent[-1][1]
    asyncio.run(bot.handle("1", BTN_PLUS, "Owner"))
    buttons = [b.callback_data for row in n.markups[-1].inline_keyboard for b in row]
    assert buttons == ["plus:Essential", "plus:Extra", "plus:Premium"]


def test_plus_and_account_buttons(tmp_path):
    bot, db, n = make_bot(tmp_path)
    asyncio.run(bot.handle_button("1", "plus:Extra", "Owner"))
    assert "2× ¥5,000" in n.sent[-1][1]
    asyncio.run(bot.handle_button("1", "acct:US", "Owner"))
    assert db.get_user("1")["regions"] == ["IN", "JP"]
    asyncio.run(bot.handle_button("1", "acct:US", "Owner"))
    assert db.get_user("1")["regions"] == ["IN", "US", "JP"]


def test_game_list_buttons_and_remove(tmp_path):
    bot, db, n = make_bot(tmp_path)
    db.add_watch("1", "https://store.playstation.com/en-us/concept/10000730", "Grand Theft Auto VI", "10000730")
    asyncio.run(bot.handle("1", "/list", "Owner"))
    rows = n.markups[-1].inline_keyboard
    assert rows[0][0].text.startswith("Grand Theft Auto VI") and "₪207" in rows[0][0].text
    wid = rows[0][0].callback_data.split(":")[1]
    asyncio.run(bot.handle_button("1", f"g:{wid}", "Owner"))
    assert "1× ₹5,000" in n.sent[-1][1]
    asyncio.run(bot.handle_button("1", f"rm:{wid}", "Owner"))
    assert db.watch_rows("1") == []


def test_commands_menu_set_once(tmp_path):
    bot, db, n = make_bot(tmp_path)
    n.get_updates = lambda offset: _empty()
    asyncio.run(bot.process_inbox())
    assert n.commands[0][0] == "start"
    n.commands = None
    asyncio.run(bot.process_inbox())
    assert n.commands is None


async def _empty():
    return []
