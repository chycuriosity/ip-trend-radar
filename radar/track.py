"""Deep tracking: call MediaCrawler via subprocess for keyword search."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml

from .storage import init_db, save_tracked_content

TZ = timezone(timedelta(hours=8))

# Priority: 1) Parent dir MediaCrawler (local dev)  2) crawler submodule (GitHub Actions)
for candidate in [
    Path(__file__).parent.parent.parent / "MediaCrawler",
    Path(__file__).parent.parent / "crawler",
]:
    for py in [candidate / ".venv" / "Scripts" / "python.exe",  # Windows
               candidate / ".venv" / "bin" / "python"]:         # Linux
        if py.exists():
            MEDIACRAWLER_DIR = candidate
            MEDIACRAWLER_PYTHON = py
            break
    else:
        continue
    break


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_item(item: dict, platform: str, topic_label: str) -> Optional[dict]:
    title = (item.get("title") or item.get("display_title") or
             item.get("desc") or item.get("content", ""))
    if not title or len(str(title)) < 2:
        return None

    # Skip comment entries (they have comment_id field)
    if "comment_id" in item:
        return None

    likes = comments = shares = views = collects = 0
    author_name = ""
    content_id = str(item.get("id") or item.get("note_id") or item.get("mblogid") or
                     item.get("aid") or item.get("bvid") or "")

    if platform == "wb":
        likes = int(item.get("attitudes_count", 0))
        comments = int(item.get("comments_count", 0))
        shares = int(item.get("reposts_count", 0))
        content_id = str(item.get("mblogid") or item.get("note_id") or content_id)
        user = item.get("user", {}) if isinstance(item.get("user"), dict) else {}
        author_name = user.get("screen_name", "")
    elif platform == "bili":
        stat = item.get("stat", {}) if isinstance(item.get("stat"), dict) else {}
        likes = int(stat.get("like", 0))
        comments = int(stat.get("reply", 0))
        shares = int(stat.get("share", 0))
        views = int(stat.get("view", 0))
        content_id = str(item.get("aid") or item.get("bvid") or content_id)
        owner = item.get("owner", {}) if isinstance(item.get("owner"), dict) else {}
        author_name = owner.get("name", "")
    elif platform == "zhihu":
        likes = int(item.get("voteup_count", 0))
        comments = int(item.get("comment_count", 0))
        author = item.get("author", {}) if isinstance(item.get("author"), dict) else {}
        author_name = author.get("name", "")
    elif platform == "xhs":
        likes = int(item.get("liked_count", 0))
        comments = int(item.get("comment_count", 0))
        shares = int(item.get("shared_count", 0))
        collects = int(item.get("collected_count", 0))
        content_id = str(item.get("note_id") or content_id)
        user = item.get("user", {}) if isinstance(item.get("user"), dict) else {}
        author_name = user.get("nickname") or user.get("nick_name", "")

    return {
        "topic_label": topic_label,
        "platform": platform,
        "content_id": content_id,
        "title": title[:200],
        "url": item.get("url", ""),
        "author_name": author_name,
        "author_followers": 0,
        "content_created_at": "",
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "views": views,
        "collects": collects,
        "extra": {},
    }


def _parse_output(output_dir: str, platform: str, topic_label: str) -> list[dict]:
    results = []
    data_path = Path(output_dir)
    if not data_path.exists():
        return results

    for jsonl_file in data_path.glob("**/*.jsonl"):
        try:
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    normalized = _normalize_item(item, platform, topic_label)
                    if normalized and normalized["title"]:
                        results.append(normalized)
        except Exception:
            pass
    return results


def run_tracking(topic_label: str, keywords: list[str], platforms: Optional[list[str]] = None):
    """Run MediaCrawler deep search for a topic across configured platforms."""
    config = load_config()
    tracking_platforms = config.get("tracking_platforms", [])

    if platforms:
        tracking_platforms = [p for p in tracking_platforms if p["id"] in platforms]

    keyword_str = ",".join(keywords[:3])
    all_results = []

    for p in tracking_platforms:
        pid = p["id"]
        env_key = p.get("cookie_env", "")
        cookie = os.environ.get(env_key, "")

        if not cookie:
            print(f"[track] Skipping {p['name']}: no cookie (env {env_key})")
            continue

        base = Path(__file__).parent.parent  # ip-trend-radar root
        output_dir = str((base / "data" / "tracking" / f"{topic_label.replace('/', '_')}_{pid}").absolute())
        print(f"[track] {p['name']}: searching '{keyword_str}'...")

        cmd = [
            str(MEDIACRAWLER_PYTHON), "main.py",
            "--platform", pid,
            "--lt", "cookie",
            "--cookies", cookie,
            "--keywords", keyword_str,
            "--type", "search",
            "--headless", "yes",
            "--save_data_option", "jsonl",
            "--save_data_path", output_dir,
        ]

        try:
            log_file = Path(output_dir) / "crawl.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "w", encoding="utf-8") as log:
                result = subprocess.run(
                    cmd,
                    cwd=str(MEDIACRAWLER_DIR),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                )

            # Dump log for debugging
            if log_file.exists():
                log_content = log_file.read_text(encoding="utf-8", errors="replace")
                # Print last 10 lines of relevant output
                for line in log_content.split("\n")[-15:]:
                    if line.strip():
                        print(f"    {line[:150]}")

            if result.returncode == 0:
                items = _parse_output(output_dir, pid, topic_label)
                if not items:
                    # Also check crawler's own data dir
                    alt_dir = MEDIACRAWLER_DIR / "data"
                    items = _parse_output(str(alt_dir), pid, topic_label)
                print(f"  [{pid}] OK: {len(items)} items")
                all_results.extend(items)
            else:
                print(f"  [{pid}] Exit {result.returncode}")
        except subprocess.TimeoutExpired:
            print(f"  [{pid}] Timeout (>5min)")
        except Exception as e:
            print(f"  [{pid}] Error: {e}")

    if all_results:
        init_db()
        save_tracked_content(all_results, topic_label)
        print(f"\n[track] Total: {len(all_results)} items for '{topic_label}'")
    else:
        print(f"\n[track] No results for '{topic_label}'")

    return all_results
