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
