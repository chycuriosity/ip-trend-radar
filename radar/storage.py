"""SQLite storage for hotlist snapshots, detected topics, and tracked content."""
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

DB_DIR = Path("data")
DB_PATH = DB_DIR / "trend_radar.db"

TZ_SHANGHAI = timezone(timedelta(hours=8))


def get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS hotlist_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_time TEXT NOT NULL,
            platform TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT DEFAULT '',
            rank INTEGER DEFAULT 0,
            hot_metric TEXT DEFAULT '',
            raw_data TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS detected_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_time TEXT NOT NULL,
            topic_label TEXT NOT NULL,
            platforms TEXT NOT NULL,
            heat_score REAL DEFAULT 0,
            is_new INTEGER DEFAULT 0,
            growth_rate REAL DEFAULT 0,
            item_count INTEGER DEFAULT 0,
            related_titles TEXT DEFAULT '[]',
            ai_summary TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS tracked_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_label TEXT NOT NULL,
            platform TEXT NOT NULL,
            content_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            url TEXT DEFAULT '',
            author_name TEXT DEFAULT '',
            author_followers INTEGER DEFAULT 0,
            content_created_at TEXT DEFAULT '',
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            collects INTEGER DEFAULT 0,
            extra JSON DEFAULT '{}',
            crawl_time TEXT NOT NULL,
            UNIQUE(topic_label, platform, content_id)
        );

        CREATE TABLE IF NOT EXISTS crawl_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            platform TEXT NOT NULL,
            last_crawl_time TEXT DEFAULT '',
            last_content_count INTEGER DEFAULT 0,
            UNIQUE(keyword, platform)
        );

        CREATE INDEX IF NOT EXISTS idx_hotlist_time ON hotlist_snapshots(fetch_time);
        CREATE INDEX IF NOT EXISTS idx_topics_time ON detected_topics(fetch_time);
        CREATE INDEX IF NOT EXISTS idx_topics_label ON detected_topics(topic_label);
        CREATE INDEX IF NOT EXISTS idx_tracked_topic ON tracked_content(topic_label);
    """)
    conn.commit()
    conn.close()


def save_hotlist_snapshots(platform: str, items: list[dict], fetch_time: str):
    conn = get_db()
    for item in items:
        conn.execute(
            "INSERT INTO hotlist_snapshots (fetch_time, platform, title, url, rank, hot_metric) VALUES (?, ?, ?, ?, ?, ?)",
            (fetch_time, platform, item["title"], item.get("url", ""), item.get("rank", 0), str(item.get("hot_metric", "")))
        )
    conn.commit()
    conn.close()


def save_detected_topics(topics: list[dict], fetch_time: str):
    conn = get_db()
    for t in topics:
        conn.execute(
            "INSERT INTO detected_topics (fetch_time, topic_label, platforms, heat_score, is_new, growth_rate, item_count, related_titles) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fetch_time, t["topic_label"], json.dumps(t["platforms"]), t["heat_score"], t["is_new"], t["growth_rate"], t["item_count"], json.dumps(t.get("related_titles", []), ensure_ascii=False))
        )
    conn.commit()
    conn.close()


def save_tracked_content(items: list[dict], topic_label: str):
    conn = get_db()
    for item in items:
        conn.execute(
            """INSERT OR REPLACE INTO tracked_content
               (topic_label, platform, content_id, title, url, author_name, author_followers,
                content_created_at, likes, comments, shares, views, collects, extra, crawl_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (topic_label, item["platform"], item["content_id"], item["title"], item.get("url", ""),
             item.get("author_name", ""), item.get("author_followers", 0), item.get("content_created_at", ""),
             item.get("likes", 0), item.get("comments", 0), item.get("shares", 0),
             item.get("views", 0), item.get("collects", 0),
             json.dumps(item.get("extra", {}), ensure_ascii=False),
             datetime.now(TZ_SHANGHAI).isoformat())
        )
    conn.commit()
    conn.close()


def get_recent_topics(hours: int = 24) -> list[dict]:
    conn = get_db()
    cutoff = (datetime.now(TZ_SHANGHAI) - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT * FROM detected_topics WHERE fetch_time >= ? ORDER BY heat_score DESC", (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_topic_history(topic_label: str, days: int = 7) -> list[dict]:
    conn = get_db()
    cutoff = (datetime.now(TZ_SHANGHAI) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM detected_topics WHERE topic_label = ? AND fetch_time >= ? ORDER BY fetch_time ASC",
        (topic_label, cutoff)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tracked_content(topic_label: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tracked_content WHERE topic_label = ? ORDER BY likes DESC", (topic_label,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_summary(date_str: Optional[str] = None) -> dict:
    if date_str is None:
        date_str = datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")
    conn = get_db()
    topics = conn.execute(
        "SELECT * FROM detected_topics WHERE fetch_time LIKE ? ORDER BY heat_score DESC",
        (f"{date_str}%",)
    ).fetchall()
    total_hotlist = conn.execute(
        "SELECT COUNT(*) as cnt FROM hotlist_snapshots WHERE fetch_time LIKE ?",
        (f"{date_str}%",)
    ).fetchone()
    conn.close()
    return {
        "date": date_str,
        "topic_count": len(topics),
        "hotlist_count": total_hotlist["cnt"] if total_hotlist else 0,
        "topics": [dict(t) for t in topics[:30]],
    }
