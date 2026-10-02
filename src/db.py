"""SQLite state: users + watchlists, last alerts, daily price lows, source health, snapshot.

Kept small on purpose: the DB is saved to the GitHub Actions cache after every run
(every 5 minutes for the Telegram inbox), so there is no raw price history - only
one lowest price per card value per day.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.models import Offer, SourceResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_low (
    day TEXT NOT NULL,
    region TEXT NOT NULL,
    face INTEGER NOT NULL,
    effective_ils REAL NOT NULL,
    PRIMARY KEY (day, region, face)
);

CREATE TABLE IF NOT EXISTS alerts (
    face_inr INTEGER PRIMARY KEY,
    store TEXT NOT NULL,
    effective_ils REAL NOT NULL,
    alerted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_prices (
    concept_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    best_region TEXT NOT NULL,
    effective_ils REAL NOT NULL,
    baseline_ils REAL NOT NULL,     -- last alerted (or last higher) price; a drop below it alerts
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    chat_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    approved INTEGER NOT NULL DEFAULT 0,
    regions TEXT NOT NULL DEFAULT 'IN,US,JP',   -- PSN accounts this user has
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watches (
    chat_id TEXT NOT NULL,
    line TEXT NOT NULL,             -- PS Store link as the user sent it
    title TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (chat_id, line)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
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
        self._migrate()

    def _migrate(self) -> None:
        """v1/v2 kept every offer of every run; fold that into daily lows and drop it."""
        tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "offers" not in tables:
            return
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(offers)")]
        region = "region" if "region" in cols else "'IN'"
        self.conn.execute(
            f"INSERT OR IGNORE INTO daily_low SELECT substr(run_at,1,10), {region}, face_inr, "
            "MIN(effective_ils) FROM offers WHERE in_stock=1 AND effective_ils IS NOT NULL "
            f"GROUP BY substr(run_at,1,10), {region}, face_inr"
        )
        self.conn.execute("DROP TABLE offers")
        self.conn.commit()
        self.conn.execute("VACUUM")

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # ---- prices -------------------------------------------------------------

    def save_daily_lows(self, offers: list[Offer]) -> None:
        day = now_iso()[:10]
        for o in offers:
            if not o.in_stock or o.effective_ils is None:
                continue
            self.conn.execute(
                "INSERT INTO daily_low VALUES (?,?,?,?) ON CONFLICT(day, region, face) "
                "DO UPDATE SET effective_ils=MIN(effective_ils, excluded.effective_ils)",
                (day, o.region, o.face, o.effective_ils),
            )
        self.conn.execute("DELETE FROM daily_low WHERE day < date('now', '-90 days')")

    def lowest_seen(self, face: int, days: int = 30, region: str = "IN") -> Optional[float]:
        row = self.conn.execute(
            "SELECT MIN(effective_ils) FROM daily_low WHERE region=? AND face=? "
            "AND day >= date('now', ?)",
            (region, face, f"-{days} days"),
        ).fetchone()
        return row[0] if row else None

    def last_alert_ils(self, face: int) -> Optional[float]:
        row = self.conn.execute(
            "SELECT effective_ils FROM alerts WHERE face_inr=?", (face,)
        ).fetchone()
        return row[0] if row else None

    def record_alert(self, offer: Offer) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO alerts VALUES (?,?,?,?)",
            (offer.face, offer.store, offer.effective_ils, now_iso()),
        )

    def clear_alert(self, face: int) -> None:
        """Deal is gone - the next good deal (e.g. a restock) alerts again."""
        self.conn.execute("DELETE FROM alerts WHERE face_inr=?", (face,))

    def game_baseline(self, concept_id: str) -> Optional[float]:
        row = self.conn.execute(
            "SELECT baseline_ils FROM game_prices WHERE concept_id=?", (concept_id,)
        ).fetchone()
        return row[0] if row else None

    def save_game(self, concept_id: str, title: str, best_region: str,
                  effective_ils: float, baseline_ils: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO game_prices VALUES (?,?,?,?,?,?)",
            (concept_id, title, best_region, effective_ils, baseline_ils, now_iso()),
        )

    # ---- users & watchlists -------------------------------------------------

    def ensure_owner(self, chat_id: str) -> None:
        """The bot's owner (TELEGRAM_CHAT_ID) is always an approved user."""
        if chat_id:
            self.conn.execute(
                "INSERT INTO users (chat_id, name, approved, created_at) VALUES (?, 'owner', 1, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET approved=1",
                (chat_id, now_iso()),
            )

    def get_user(self, chat_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT chat_id, name, approved, regions FROM users WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if not row:
            return None
        return {"chat_id": row[0], "name": row[1], "approved": bool(row[2]),
                "regions": [r for r in row[3].split(",") if r]}

    def add_pending_user(self, chat_id: str, name: str) -> bool:
        """Returns True if this is a new user (so the owner should be asked)."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO users (chat_id, name, approved, created_at) VALUES (?,?,0,?)",
            (chat_id, name, now_iso()),
        )
        return cur.rowcount == 1

    def approve_user(self, chat_id: str) -> bool:
        return self.conn.execute(
            "UPDATE users SET approved=1 WHERE chat_id=?", (chat_id,)).rowcount == 1

    def remove_user(self, chat_id: str) -> None:
        self.conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id,))
        self.conn.execute("DELETE FROM watches WHERE chat_id=?", (chat_id,))

    def set_regions(self, chat_id: str, regions: list[str]) -> None:
        self.conn.execute("UPDATE users SET regions=? WHERE chat_id=?", (",".join(regions), chat_id))

    def approved_users(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT chat_id, name, regions FROM users WHERE approved=1 ORDER BY created_at"
        ).fetchall()
        return [{"chat_id": r[0], "name": r[1], "regions": [x for x in r[2].split(",") if x]}
                for r in rows]

    def all_users(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT chat_id, name, approved FROM users ORDER BY created_at").fetchall()
        return [{"chat_id": r[0], "name": r[1], "approved": bool(r[2])} for r in rows]

    def add_watch(self, chat_id: str, line: str, title: str = "") -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO watches VALUES (?,?,?)", (chat_id, line, title))
        return cur.rowcount == 1

    def remove_watch(self, chat_id: str, line: str) -> None:
        self.conn.execute("DELETE FROM watches WHERE chat_id=? AND line=?", (chat_id, line))

    def watches(self, chat_id: Optional[str] = None) -> list[tuple[str, str, str]]:
        """(chat_id, line, title) rows, for one user or everyone."""
        if chat_id:
            return self.conn.execute(
                "SELECT chat_id, line, title FROM watches WHERE chat_id=? ORDER BY rowid",
                (chat_id,)).fetchall()
        return self.conn.execute("SELECT chat_id, line, title FROM watches ORDER BY rowid").fetchall()

    def set_watch_title(self, line: str, title: str) -> None:
        self.conn.execute("UPDATE watches SET title=? WHERE line=?", (title, line))

    # ---- misc -----------------------------------------------------------------

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def get_snapshot(self) -> dict:
        raw = self.get_meta("snapshot")
        return json.loads(raw) if raw else {}

    def update_snapshot(self, **parts) -> None:
        """Latest prices for the Telegram commands, so replies need no scraping."""
        snap = self.get_snapshot()
        snap.update(parts)
        self.set_meta("snapshot", json.dumps(snap, ensure_ascii=False))

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
