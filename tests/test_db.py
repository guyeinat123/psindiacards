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


def test_lowest_seen_ignores_out_of_stock(tmp_path):
    db = make_db(tmp_path)
    run = now_iso()
    db.save_offers([
        Offer("t", "A", 1000, 1, "INR", "u", effective_ils=40.0, markup_pct=1),
        Offer("t", "B", 1000, 1, "INR", "u", in_stock=False, effective_ils=30.0, markup_pct=1),
    ], run)
    assert db.lowest_seen(1000) == 40.0


def test_broken_source_notified_once_then_resets(tmp_path):
    db = make_db(tmp_path)
    bad, good = SourceResult("seagm", "blocked"), SourceResult("seagm", "ok")
    assert [db.update_health(bad, 3) for _ in range(5)] == [False, False, True, False, False]
    db.update_health(good, 3)
    assert [db.update_health(bad, 3) for _ in range(3)] == [False, False, True]
    assert db.update_health(SourceResult("amazon_in", "skipped"), 1) is False


def test_v1_database_gets_region_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE offers (run_at TEXT, source TEXT, store TEXT, face_inr INTEGER, price REAL, "
                "currency TEXT, effective_ils REAL, markup_pct REAL, in_stock INTEGER, url TEXT)")
    old.execute("INSERT INTO offers VALUES ('2026-10-01 00:00:00','s','S',1000,1,'INR',40,1,1,'u')")
    old.commit(); old.close()
    db = DB(str(path))
    db.save_offers([Offer("t", "A", 50, 47, "USD", "u", region="US", effective_ils=150, markup_pct=-4)], now_iso())
    regions = [r[0] for r in db.conn.execute("SELECT region FROM offers ORDER BY run_at")]
    assert regions == ["IN", "US"]


def test_game_baseline_and_meta(tmp_path):
    db = make_db(tmp_path)
    assert db.game_baseline("1") is None
    db.save_game("1", "Game", "US", 200.0, 200.0)
    assert db.game_baseline("1") == 200.0
    db.set_meta("games_last_run", "2026-10-02 00:00:00")
    assert db.get_meta("games_last_run") == "2026-10-02 00:00:00"
