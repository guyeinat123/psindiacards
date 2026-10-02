"""SQLite state: price history, last alert per card value, source health."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models import Offer, SourceResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    run_at TEXT NOT NULL,
    source TEXT NOT NULL,
    store TEXT NOT NULL,
    face_inr INTEGER NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    effective_ils REAL,
    markup_pct REAL,
    in_stock INTEGER NOT NULL,
    url TEXT
);
CREATE INDEX IF NOT EXISTS offers_face_run ON offers(face_inr, run_at);

CREATE TABLE IF NOT EXISTS alerts (
    face_inr INTEGER PRIMARY KEY,
    store TEXT NOT NULL,
    effective_ils REAL NOT NULL,
    alerted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_status TEXT,
    last_ok_at TEXT,
    broken_notified INTEGER NOT NULL DEFAULT 0
);
"""


def now_iso() -> str:
    """UTC in SQLite's own format, so comparisons with datetime('now', ...) are exact."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class DB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def save_offers(self, offers: list[Offer], run_at: str) -> None:
        self.conn.executemany(
            "INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(run_at, o.source, o.store, o.face_inr, o.price, o.currency,
              o.effective_ils, o.markup_pct, int(o.in_stock), o.url) for o in offers],
        )
        self.conn.execute("DELETE FROM offers WHERE run_at < datetime('now', '-45 days')")

    def last_alert_ils(self, face_inr: int) -> Optional[float]:
        row = self.conn.execute(
            "SELECT effective_ils FROM alerts WHERE face_inr=?", (face_inr,)
        ).fetchone()
        return row[0] if row else None

    def record_alert(self, offer: Offer) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO alerts VALUES (?,?,?,?)",
            (offer.face_inr, offer.store, offer.effective_ils, now_iso()),
        )

    def clear_alert(self, face_inr: int) -> None:
        """Deal is gone - the next good deal (e.g. a restock) alerts again."""
        self.conn.execute("DELETE FROM alerts WHERE face_inr=?", (face_inr,))

    def lowest_seen(self, face_inr: int, days: int = 30) -> Optional[float]:
        row = self.conn.execute(
            "SELECT MIN(effective_ils) FROM offers WHERE face_inr=? AND in_stock=1 "
            "AND run_at >= datetime('now', ?)",
            (face_inr, f"-{days} days"),
        ).fetchone()
        return row[0] if row else None

    def update_health(self, result: SourceResult, broken_after: int) -> bool:
        """Track failures. Returns True exactly once when a source crosses the broken threshold."""
        if result.status == "skipped":
            return False
        row = self.conn.execute(
            "SELECT consecutive_failures, broken_notified FROM source_health WHERE source=?",
            (result.source,),
        ).fetchone()
        failures, notified = row if row else (0, 0)
        if result.status == "ok":
            self.conn.execute(
                "INSERT OR REPLACE INTO source_health VALUES (?,0,'ok',?,0)",
                (result.source, now_iso()),
            )
            return False
        failures += 1
        newly_broken = failures >= broken_after and not notified
        self.conn.execute(
            "INSERT INTO source_health (source, consecutive_failures, last_status, broken_notified) "
            "VALUES (?,?,?,?) ON CONFLICT(source) DO UPDATE SET "
            "consecutive_failures=excluded.consecutive_failures, last_status=excluded.last_status, "
            "broken_notified=excluded.broken_notified",
            (result.source, failures, result.status, int(notified or newly_broken)),
        )
        return newly_broken
