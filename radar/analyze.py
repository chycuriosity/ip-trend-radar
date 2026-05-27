"""Analysis engine: propagation path, trend detection, AI summarization."""
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional

import numpy as np

from .storage import get_tracked_content, get_topic_history, get_recent_topics

TZ = timezone(timedelta(hours=8))


def analyze_propagation(topic_label: str) -> dict:
    """Analyze which platform a topic appeared on first, and how it spread."""
    items = get_tracked_content(topic_label)
    if not items:
        return {"topic_label": topic_label, "propagation_path": [], "origin_platform": None}

    # Group by platform, find earliest content
    # Use content_created_at or crawl_time as fallback
    platform_first = defaultdict(list)
    for item in items:
        ts = item.get("content_created_at", "") or item.get("crawl_time", "")
        if ts:
            platform_first[item["platform"]].append(ts)

    # Sort platforms by first appearance
    platform_earliest = {}
    for platform, times in platform_first.items():
        sorted_times = sorted(times)
        platform_earliest[platform] = min(sorted_times)

    path = sorted(platform_earliest.items(), key=lambda x: x[1])

    if not path:
        return {"topic_label": topic_label, "propagation_path": [], "origin_platform": None}

    result = [{
        "platform": path[0][0],
        "first_seen": path[0][1],
        "delay": "0h",
    }]

    if len(path) > 1:
        first_time = datetime.fromisoformat(path[0][1])
        for p, t in path[1:]:
            this_time = datetime.fromisoformat(t)
            delay_hours = round((this_time - first_time).total_seconds() / 3600, 1)
            result.append({
                "platform": p,
                "first_seen": t,
                "delay": f"+{delay_hours}h",
            })

    return {
        "topic_label": topic_label,
        "propagation_path": result,
        "origin_platform": path[0][0] if path else None,
    }


def detect_burst(topic_label: str, window_days: int = 7) -> dict:
    """Detect if a topic is experiencing a burst (Z-score method)."""
    history = get_topic_history(topic_label, days=window_days * 2)

    if len(history) < 5:
        return {"is_burst": False, "z_score": 0, "message": "Not enough history data"}

    # Group by time buckets and compute heat
    scores = [h["heat_score"] for h in history]
    recent_scores = scores[-window_days:] if len(scores) > window_days else scores
    baseline_scores = scores[:-window_days] if len(scores) > window_days else scores[:len(scores)//2]

    if len(baseline_scores) < 2:
        return {"is_burst": False, "z_score": 0, "message": "Not enough baseline data"}

    mean = np.mean(baseline_scores)
    std = np.std(baseline_scores)
    if std == 0:
        std = 1

    current = recent_scores[-1] if recent_scores else 0
    z_score = (current - mean) / std

    return {
        "is_burst": z_score > 3.0,
        "z_score": round(z_score, 2),
        "current_heat": current,
        "baseline_mean": round(mean, 1),
        "baseline_std": round(std, 1),
        "message": f"Heat burst detected! ({z_score:.1f}x std)" if z_score > 3.0 else f"Normal fluctuation ({z_score:.1f}x std)",
    }


def generate_ai_summary(topic_label: str, api_key: Optional[str] = None,
                        api_base: Optional[str] = None, model: Optional[str] = None) -> str:
    """Generate a natural language summary of a topic using LLM."""
    api_key = api_key or os.environ.get("AI_API_KEY", "")
    if not api_key:
        return "（未配置 AI API Key，无法生成摘要）"

    model = model or os.environ.get("AI_MODEL", "deepseek-chat")
    api_base = api_base or os.environ.get("AI_API_BASE", "https://api.deepseek.com/v1")

    items = get_tracked_content(topic_label)
    propagation = analyze_propagation(topic_label)
    burst = detect_burst(topic_label)

    if not items:
        return f"未找到关于「{topic_label}」的内容数据。"

    # Build structured prompt
    platforms_data = defaultdict(list)
    for item in items:
        platforms_data[item["platform"]].append(item)

    data_section = f"话题：{topic_label}\n\n传播路径：\n"
    for step in propagation.get("propagation_path", []):
        data_section += f"  {step['platform']} 首次出现: {step['first_seen']} ({step['delay']})\n"

    data_section += f"\n热度状态: {burst['message']}\n\n"
    data_section += "各平台热门内容：\n"

    for platform, plat_items in platforms_data.items():
        data_section += f"\n[{platform}] {len(plat_items)} 条内容\n"
        sorted_items = sorted(plat_items, key=lambda x: x["likes"] + x["comments"], reverse=True)
        for item in sorted_items[:5]:
            data_section += f"  - {item['title'][:60]} (赞:{item['likes']} 评:{item['comments']})\n"

    prompt = f"""你是一个专业的热点舆情分析师。请根据以下数据，用200字以内的中文对该话题进行一句话总结，包括：
1. 热点概述
2. 传播态势（哪个平台最先出现、扩散情况）
3. 值得关注的信号

{data_section}

请直接输出分析结果，不要前缀。"""

    try:
        import litellm
        response = litellm.completion(
            model=f"openai/{model}",
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            api_base=api_base,
            max_tokens=300,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI 摘要生成失败: {e}"


def generate_daily_report() -> dict:
    """Generate a daily trend report."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    topics = get_recent_topics(hours=24)

    new_topics = [t for t in topics if t["is_new"]]
    top_topics = sorted(topics, key=lambda t: t["heat_score"], reverse=True)[:20]

    # Platform contribution stats
    platform_counts = defaultdict(int)
    for t in topics:
        for p in json_loads(t.get("platforms", "[]")):
            platform_counts[p] += 1

    return {
        "date": today,
        "total_topics": len(topics),
        "new_topics": len(new_topics),
        "top_topics": top_topics,
        "new_signals": [t for t in new_topics if t["heat_score"] >= 70],
        "platform_contributions": dict(platform_counts),
    }


def json_loads(s, default=None):
    import json
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []
