import hashlib
import sqlite3

from datetime import datetime, timezone

from pathlib import Path

from config import DB_FILE


def _connect():
    Path(DB_FILE).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = sqlite3.connect(DB_FILE)

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    with _connect() as conn:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS processed_news (
                news_hash TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT,
                published_at TEXT,
                currency TEXT,
                timestamp TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS analyzed_events (
                event_hash TEXT PRIMARY KEY,
                event_name TEXT NOT NULL,
                event_date TEXT,
                timestamp TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS alerts (
                alert_hash TEXT PRIMARY KEY,
                topic_hash TEXT NOT NULL,
                asset TEXT,
                title TEXT,
                sent_at TEXT NOT NULL
            );


            CREATE INDEX IF NOT EXISTS idx_alerts_topic
            ON alerts(topic_hash);


            CREATE INDEX IF NOT EXISTS idx_alerts_sent_at
            ON alerts(sent_at);
            """
        )


def stable_hash(*parts: str) -> str:

    normalized = "|".join(
        (p or "").strip().lower()
        for p in parts
    )

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def news_hash(
    title: str,
    url: str = "",
) -> str:

    return stable_hash(
        title,
        url,
    )


def event_hash(
    event: dict,
    currency: str,
) -> str:

    return stable_hash(
        str(event.get("name", "")),
        str(event.get("title", "")),
        str(event.get("date", "")),
        str(event.get("time_utc", "")),
        currency,
        str(event.get("actual", "")),
    )


def topic_hash(
    title: str,
    asset: str,
) -> str:

    return stable_hash(
        title,
        asset,
    )


def is_news_processed(h: str) -> bool:

    with _connect() as conn:

        row = conn.execute(
            """
            SELECT 1
            FROM processed_news
            WHERE news_hash = ?
            """,
            (h,),
        ).fetchone()

    return row is not None


def mark_news_processed(
    h: str,
    title: str,
    url: str,
    published_at: str,
    currency: str,
):

    with _connect() as conn:

        conn.execute(
            """
            INSERT OR IGNORE INTO processed_news
            (
                news_hash,
                title,
                url,
                published_at,
                currency,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                h,
                title,
                url,
                published_at,
                currency,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )


def is_event_processed(h: str) -> bool:

    with _connect() as conn:

        row = conn.execute(
            """
            SELECT 1
            FROM analyzed_events
            WHERE event_hash = ?
            """,
            (h,),
        ).fetchone()

    return row is not None


def mark_event_processed(
    h: str,
    name: str,
    event_date: str,
):

    with _connect() as conn:

        conn.execute(
            """
            INSERT OR IGNORE INTO analyzed_events
            (
                event_hash,
                event_name,
                event_date,
                timestamp
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                h,
                name,
                event_date,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )


def alert_allowed(
    topic: str,
    cooldown_minutes: int,
) -> bool:

    with _connect() as conn:

        row = conn.execute(
            """
            SELECT sent_at
            FROM alerts
            WHERE topic_hash = ?
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            (topic,),
        ).fetchone()

    if not row:
        return True

    last = datetime.fromisoformat(
        row["sent_at"]
    )

    age_seconds = (
        datetime.now(timezone.utc) - last
    ).total_seconds()

    return age_seconds >= (
        cooldown_minutes * 60
    )


def mark_alert_sent(
    alert_h: str,
    topic: str,
    asset: str,
    title: str,
):

    with _connect() as conn:

        conn.execute(
            """
            INSERT OR REPLACE INTO alerts
            (
                alert_hash,
                topic_hash,
                asset,
                title,
                sent_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                alert_h,
                topic,
                asset,
                title,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )