"""Discovery layer: fetch hotlists → cluster cross-platform → detect trends."""
import json
import os
import time
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional

import numpy as np
import yaml
from sentence_transformers import SentenceTransformer

from .storage import init_db, save_hotlist_snapshots, save_detected_topics, get_recent_topics

TZ = timezone(timedelta(hours=8))

NEWSNOW_API = "https://newsnow.busiyi.world/api/s"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# Lazy-loaded model
_model: Optional[SentenceTransformer] = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print("[discover] Loading embedding model...")
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        print("[discover] Model loaded")
    return _model


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    # Resolve ${VAR:-default} env var references
    def resolve(obj):
        if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            inner = obj[2:-1]
            parts = inner.split(":-", 1)
            return os.environ.get(parts[0], parts[1] if len(parts) > 1 else "")
        elif isinstance(obj, dict):
            return {k: resolve(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [resolve(v) for v in obj]
        return obj
    return resolve(raw)


def fetch_all_hotlists(platforms: list[dict]) -> list[dict]:
    """Fetch hotlists from all configured platforms via NewsNow API."""
    all_items = []
    fetch_time = datetime.now(TZ).isoformat()

    for p in platforms:
        pid = p["id"]
        try:
            resp = requests.get(f"{NEWSNOW_API}?id={pid}&latest", headers=HEADERS, timeout=15)
            data = resp.json()
            items = data.get("items", [])
            status = data.get("status", "?")
            print(f"  [{pid:25s}] {status:7s}  {len(items):3d} items")

            normalized = []
            for idx, item in enumerate(items):
                title = item.get("title", "")
                if not title or not isinstance(title, str) or not title.strip():
                    continue
                normalized.append({
                    "platform": pid,
                    "platform_name": p.get("name", pid),
                    "title": title.strip(),
                    "url": item.get("url", ""),
                    "rank": idx + 1,
                    "hot_metric": "",
                })

            save_hotlist_snapshots(pid, normalized, fetch_time)
            all_items.extend(normalized)
            time.sleep(0.3)

        except Exception as e:
            print(f"  [{pid}] ERROR: {e}")

    print(f"\n[discover] Total items fetched: {len(all_items)} from {len(platforms)} platforms")
    return all_items


def cluster_cross_platform(items: list[dict], config: dict) -> list[dict]:
    """Cluster similar titles across platforms using sentence-transformers."""
    if len(items) < 2:
        return []

    threshold = config.get("clustering", {}).get("similarity_threshold", 0.65)
    min_platforms = config.get("clustering", {}).get("min_platforms_for_trend", 2)

    model = get_model()
    titles = [item["title"] for item in items]
    embeddings = model.encode(titles, show_progress_bar=True)

    # Compute pairwise cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normalized = embeddings / norms
    sim_matrix = np.dot(normalized, normalized.T)

    # Simple greedy clustering
    used = set()
    clusters = []

    for i in range(len(items)):
        if i in used:
            continue
        cluster_indices = [i]
        for j in range(i + 1, len(items)):
            if j not in used and sim_matrix[i][j] >= threshold:
                cluster_indices.append(j)

        if len(cluster_indices) >= min_platforms:
            cluster_items = [items[idx] for idx in cluster_indices]
            platforms = list(set(it["platform"] for it in cluster_items))

            if len(platforms) >= min_platforms:
                clusters.append({
                    "items": cluster_items,
                    "platforms": platforms,
                    "titles": [it["title"] for it in cluster_items],
                })

        used.update(cluster_indices)

    print(f"[discover] Clusters found: {len(clusters)} (min {min_platforms}+ platforms)")
    return clusters


def compute_topic_label(cluster: dict) -> str:
    """Extract a short topic label from a cluster. Uses the shortest common title."""
    titles = cluster["titles"]
    # Heuristic: find the most representative title (shortest non-empty)
    sorted_titles = sorted(titles, key=len)
    for t in sorted_titles:
        if 4 <= len(t) <= 30:
            return t
    return sorted_titles[0][:30] if sorted_titles else "未知话题"


def detect_new_trends(clusters: list[dict], fetch_time: str) -> list[dict]:
    """Compare clusters against recent history to detect new/rising trends."""
    recent = get_recent_topics(hours=24)
    recent_labels = set(t["topic_label"] for t in recent)

    results = []
    for c in clusters:
        label = compute_topic_label(c)
        is_new = label not in recent_labels

        # Compute heat score: item_count * platform_diversity * rank_boost
        platform_count = len(c["platforms"])
        item_count = len(c["items"])
        # Average rank (lower is better)
        avg_rank = np.mean([it.get("rank", 50) for it in c["items"]])
        rank_boost = max(0, 1 - avg_rank / 50)
        heat_score = min(100, (item_count * 5 + platform_count * 15) * (0.5 + rank_boost))

        results.append({
            "topic_label": label,
            "platforms": c["platforms"],
            "heat_score": round(heat_score, 1),
            "is_new": 1 if is_new else 0,
            "growth_rate": 0.0,  # Will be computed with more history
            "item_count": item_count,
            "related_titles": c["titles"],
        })

    # Sort by heat score descending
    results.sort(key=lambda x: x["heat_score"], reverse=True)
    return results


def run_discovery(config_path: str = "config.yaml"):
    """Main discovery pipeline."""
    print("=" * 50)
    print(f"[discover] Starting at {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    init_db()
    config = load_config(config_path)
    platforms = config.get("platforms", [])

    # Phase 1: Fetch all hotlists
    print("\n[discover] Phase 1: Fetching hotlists...")
    items = fetch_all_hotlists(platforms)

    # Phase 2: Cluster cross-platform
    print("\n[discover] Phase 2: Clustering cross-platform topics...")
    clusters = cluster_cross_platform(items, config)

    # Phase 3: Detect new trends
    print("\n[discover] Phase 3: Detecting trends...")
    fetch_time = datetime.now(TZ).isoformat()
    topics = detect_new_trends(clusters, fetch_time)

    # Phase 4: Save to storage
    if topics:
        save_detected_topics(topics, fetch_time)
        print(f"\n[discover] Saved {len(topics)} topics")
        print("\n[discover] Top 10 trends:")
        for i, t in enumerate(topics[:10]):
            new_flag = " NEW" if t["is_new"] else ""
            platforms_str = "+".join(t["platforms"])
            print(f"  {i+1:2d}. [{t['heat_score']:5.1f}] {t['topic_label'][:40]:40s} | {platforms_str}{new_flag}")
    else:
        print("\n[discover] No cross-platform trends detected this round")

    print("\n[discover] Done.")
    return topics
