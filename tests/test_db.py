import sqlite3

from src.db import DB, now_iso
from src.models import Offer, SourceResult


def make_db(tmp_path):
    return DB(str(tmp_path / "t.db"))


def test_alert_roundtrip_and_clear(tmp_path):
    db = make_db(tmp_path)
    o = Offer("t", "S", 1000, 1000, "INR", "u", effective_ils=32.7, markup_pct=2.5)
    assert db.last_alert_ils(1000) is None
    db.record_alert(o)
    assert db.last_alert_ils(1000) == 32.7
    db.clear_alert(1000)
    assert db.last_alert_ils(1000) is None


def test_daily_lows_keep_minimum_and_ignore_out_of_stock(tmp_path):
    db = make_db(tmp_path)
    db.save_daily_lows([
        Offer("t", "A", 1000, 1, "INR", "u", effective_ils=40.0, markup_pct=1),
        Offer("t", "B", 1000, 1, "INR", "u", in_stock=False, effective_ils=30.0, markup_pct=1),
    ])
    db.save_daily_lows([Offer("t", "C", 1000, 1, "INR", "u", effective_ils=38.0, markup_pct=1)])
    db.save_daily_lows([Offer("t", "D", 1000, 1, "INR", "u", effective_ils=45.0, markup_pct=1)])
    assert db.lowest_seen(1000) == 38.0
    assert db.lowest_seen(1000, region="JP") is None


def test_old_offers_table_is_folded_into_daily_lows(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE offers (run_at TEXT, source TEXT, store TEXT, face_inr INTEGER, price REAL, "
                "currency TEXT, effective_ils REAL, markup_pct REAL, in_stock INTEGER, url TEXT, region TEXT)")
    today = now_iso()
    old.executemany("INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (today, "s", "S", 1000, 1, "INR", 40, 1, 1, "u", "IN"),
        (today, "s", "S", 1000, 1, "INR", 35, 1, 1, "u", "IN"),
        (today, "s", "S", 50, 1, "USD", 150, -4, 1, "u", "US"),
    ])
    old.commit(); old.close()
    db = DB(str(path))
    assert db.lowest_seen(1000) == 35
    assert db.lowest_seen(50, region="US") == 150
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "offers" not in tables


def test_broken_source_notified_once_then_resets(tmp_path):
    db = make_db(tmp_path)
    bad, good = SourceResult("seagm", "blocked"), SourceResult("seagm", "ok")
    assert [db.update_health(bad, 3) for _ in range(5)] == [False, False, True, False, False]
    db.update_health(good, 3)
    assert [db.update_health(bad, 3) for _ in range(3)] == [False, False, True]
    assert db.update_health(SourceResult("amazon_in", "skipped"), 1) is False


def test_game_baseline_and_meta(tmp_path):
    db = make_db(tmp_path)
    assert db.game_baseline("1") is None
    db.save_game("1", "Game", "US", 200.0, 200.0)
    assert db.game_baseline("1") == 200.0
    db.set_meta("games_at", "2026-10-02 00:00:00")
    assert db.get_meta("games_at") == "2026-10-02 00:00:00"


def test_users_and_watches(tmp_path):
    db = make_db(tmp_path)
    db.ensure_owner("1")
    assert db.get_user("1")["approved"]
    assert db.add_pending_user("2", "Friend") is True
    assert db.add_pending_user("2", "Friend") is False          # owner is asked only once
    assert [u["chat_id"] for u in db.approved_users()] == ["1"]
    db.approve_user("2")
    db.set_regions("2", ["IN", "JP"])
    assert db.get_user("2")["regions"] == ["IN", "JP"]
    assert db.add_watch("2", "link-a") and not db.add_watch("2", "link-a")
    db.add_watch("1", "link-a")
    db.set_watch_title("link-a", "Game A")
    assert db.watches("2") == [("2", "link-a", "Game A")]
    db.remove_user("2")
    assert db.watches() == [("1", "link-a", "Game A")]


def test_snapshot_merges_parts(tmp_path):
    db = make_db(tmp_path)
    db.update_snapshot(cards={"IN": []})
    db.update_snapshot(plans={"Extra:12": []})
    assert set(db.get_snapshot()) == {"cards", "plans"}
