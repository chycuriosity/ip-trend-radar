"""Streamlit dashboard for IP Trend Radar — 操作控制台."""
import json
import os
import sys
import io
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.storage import (get_recent_topics, get_topic_history, get_tracked_content,
                           get_daily_summary, init_db, DB_PATH)
from radar.analyze import (analyze_propagation, detect_burst, generate_ai_summary,
                           generate_daily_report)

TZ = timezone(timedelta(hours=8))
REPO = "chycuriosity/ip-trend-radar"

st.set_page_config(page_title="IP Trend Radar", page_icon="", layout="wide")


# ── Data helpers ────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_topics():
    return get_recent_topics(hours=24)


def download_latest_data():
    db_file = Path(DB_PATH)
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO}/actions/artifacts?per_page=10",
            headers=headers, timeout=10)
        artifacts = resp.json().get("artifacts", [])
        for art in artifacts:
            if art["name"] == "trend-data" and not art.get("expired", False):
                dl = requests.get(art["archive_download_url"], headers=headers, timeout=30)
                if dl.status_code == 200:
                    db_file.parent.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
                        zf.extractall(db_file.parent)
                    init_db()
                    return True
    except Exception:
        pass
    return False


def run_discover():
    """Run discovery locally."""
    status = st.empty()
    status.info("正在采集热榜...")
    try:
        from radar.discover import run_discovery as rd
        topics = rd()
        load_topics.clear()
        status.success(f"完成！发现 {len(topics)} 个热点")
        return topics
    except Exception as e:
        status.error(f"失败: {e}")
        return []


def run_track_local(topic: str, keywords: str):
    """Run tracking locally via subprocess (uses local Chrome + China IP)."""
    status = st.empty()
    progress = st.progress(0, "启动浏览器中...")
    status.info(f"本地追踪「{topic}」— 4 个平台各需 1-3 分钟，请耐心等待")

    try:
        from radar.track import run_tracking
        kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [topic]
        results = run_tracking(topic, kw)
        progress.progress(100, "追踪完成！")
        progress.empty()
        if results:
            status.success(f"完成！找到 {len(results)} 条内容 → 左侧选「话题详情」查看")
        else:
            status.warning(f"完成但未找到内容，试试换个关键词")
        load_topics.clear()
        st.session_state["sel_topic"] = topic
        return results
    except Exception as e:
        progress.empty()
        status.error(f"失败: {e}")
        return []


def run_discover():
    """Run discovery locally."""
    status = st.empty()
    status.info("正在采集热榜...")
    try:
        from radar.discover import run_discovery as rd
        progress = st.progress(0, "采集热榜中...")
        topics = rd()
        progress.progress(100, "完成！")
        progress.empty()
        load_topics.clear()
        status.success(f"完成！发现 {len(topics)} 个热点，刷新页面查看")
        return topics
    except Exception as e:
        status.error(f"失败: {e}")
        return []


# ── Sidebar ──────────────────────────────────────────────────

st.sidebar.title("控制台")
st.sidebar.caption("所有操作在左上角「导航」选页面查看结果")

# Data source
st.sidebar.subheader("数据采集")
c1, c2 = st.sidebar.columns(2)
if c1.button("刷新数据", use_container_width=True, help="从服务器下载最新热点"):
    load_topics.clear()
    if download_latest_data():
        st.success("数据已更新")
        st.rerun()
    else:
        st.warning("无新数据，稍后重试")

if c2.button("运行发现", use_container_width=True, type="primary", help="立即扫描全网热点"):
    run_discover()
    st.rerun()

# Track section
st.sidebar.divider()
st.sidebar.subheader("深度追踪")
st.sidebar.caption("使用本地 Chrome 搜索，需要电脑开机")
track_topic = st.sidebar.text_input("话题名称", placeholder="如：关晓彤剧宣人脉",
                                     key="track_topic_input")
track_keywords = st.sidebar.text_input("搜索关键词", placeholder="关晓彤,剧宣",
                                        key="track_kw_input")
if st.sidebar.button("启动追踪", use_container_width=True, type="primary"):
    if track_topic:
        run_track_local(track_topic, track_keywords or track_topic)
    else:
        st.sidebar.warning("请输入话题名称")

st.sidebar.divider()
st.sidebar.caption(f"仓库: {REPO}")
st.sidebar.caption(f"数据: {'已加载' if Path(DB_PATH).exists() else '无'}")
db_mtime = Path(DB_PATH).stat().st_mtime if Path(DB_PATH).exists() else 0
if db_mtime:
    st.sidebar.caption(f"更新: {datetime.fromtimestamp(db_mtime, TZ).strftime('%m-%d %H:%M')}")

# ── Navigation ───────────────────────────────────────────────

pages = {
    "热点雷达": "page_home",
    "话题详情": "page_detail",
    "每日报告": "page_report",
}
page = st.sidebar.radio("导航", list(pages.keys()), label_visibility="collapsed")

# ── Page: Home ───────────────────────────────────────────────

if page == "热点雷达":
    st.title("IP Trend Radar — 全网热点追踪")

    st.header("今日热点雷达")
    st.caption(f"更新于 {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}  |  每2小时自动刷新")

    topics = load_topics()

    if not topics:
        st.warning("暂无数据 — 点击左侧「运行发现」采集热榜，或「刷新数据」从服务器下载")
    else:
        new_count = sum(1 for t in topics if t["is_new"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("热点话题", len(topics))
        c2.metric("新出现", new_count)
        c3.metric("平均热度", f"{sum(t['heat_score'] for t in topics) / max(len(topics), 1):.0f}")
        c4.metric("跨平台≥3", sum(1 for t in topics if len(json.loads(t.get("platforms", "[]"))) >= 3))

        st.divider()
        st.subheader("热点排行")

        sorted_topics = sorted(topics, key=lambda t: t["heat_score"], reverse=True)
        for i, t in enumerate(sorted_topics[:30]):
            platforms = json.loads(t.get("platforms", "[]"))
            tags = " ".join([f"`{p}`" for p in platforms])
            new_badge = " **NEW**" if t["is_new"] else ""
            heat_bar = "█" * max(1, int(t["heat_score"] / 5))

            c1, c2, c3 = st.columns([5, 2, 1])
            with c1:
                st.markdown(f"**{i+1}. {t['topic_label'][:60]}**{new_badge}")
                st.caption(f"{tags}  |  {t['item_count']} 条")
            with c2:
                st.markdown(f"`{t['heat_score']:.0f}` {heat_bar}")
            with c3:
                if st.button("详情", key=f"dt_{t['id']}"):
                    st.session_state["sel_topic"] = t["topic_label"]
                    st.rerun()

        # Platform breakdown chart
        st.divider()
        st.subheader("平台热度分布")
        plat_count = {}
        for t in topics:
            for p in json.loads(t.get("platforms", "[]")):
                plat_count[p] = plat_count.get(p, 0) + 1
        if plat_count:
            fig = px.bar(x=list(plat_count.keys()), y=list(plat_count.values()),
                         title="各平台热点贡献数", labels={"x": "平台", "y": "热点数"})
            st.plotly_chart(fig, use_container_width=True)

# ── Page: Detail ──────────────────────────────────────────────

elif page == "话题详情":
    topic = st.session_state.get("sel_topic", "")
    if not topic:
        st.info("请从首页「热点排行」点击话题旁的「详情」按钮")
    else:
        st.title(f"{topic} — 深度分析")

        prop = analyze_propagation(topic)
        if prop["propagation_path"]:
            st.subheader("传播链路")
            cols = st.columns(len(prop["propagation_path"]))
            for i, step in enumerate(prop["propagation_path"]):
                cols[i].metric(step["platform"], step["delay"])
            if prop["origin_platform"]:
                st.caption(f"最早出现在: {prop['origin_platform']}")

        st.divider()
        st.subheader("热门内容")
        items = get_tracked_content(topic)
        if items:
            df = pd.DataFrame(items)
            cols = ["platform", "title", "author_name", "likes", "comments", "shares"]
            st.dataframe(df[[c for c in cols if c in df.columns]].head(20), use_container_width=True)

            stats = df.groupby("platform").agg(内容数=("content_id", "count"), 总赞=("likes", "sum")).reset_index()
            c1, c2 = st.columns(2)
            with c1:
                fig = px.pie(stats, values="内容数", names="platform", title="平台分布")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                if "comments" in df.columns:
                    fig = px.bar(df.head(20), x="title", y="likes", title="热门内容互动")
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无内容数据 — 点击左侧「启动追踪」搜索")

        st.divider()
        st.subheader("热度趋势")
        hist = get_topic_history(topic, days=7)
        if len(hist) >= 2:
            df_h = pd.DataFrame(hist)
            df_h["time"] = pd.to_datetime(df_h["fetch_time"])
            fig = px.line(df_h, x="time", y="heat_score", title=f"{topic} 7日趋势", markers=True)
            st.plotly_chart(fig, use_container_width=True)

        burst = detect_burst(topic)
        if burst.get("is_burst"):
            st.error(f"异常检测: {burst['message']}")
        else:
            st.info(f"异常检测: {burst.get('message', '数据不足')}")

        st.divider()
        st.subheader("AI 分析")
        with st.spinner("生成中..."):
            st.markdown(generate_ai_summary(topic))

# ── Page: Report ──────────────────────────────────────────────

elif page == "每日报告":
    st.title("每日热点报告")
    date = st.date_input("选择日期", datetime.now(TZ).date())
    summary = get_daily_summary(date.strftime("%Y-%m-%d"))

    c1, c2, c3 = st.columns(3)
    c1.metric("热点话题", summary["topic_count"])
    c2.metric("热榜条目", summary["hotlist_count"])
    c3.metric("数据日期", summary["date"])

    if summary["topics"]:
        st.divider()
        st.subheader("当日热点")
        for t in summary["topics"][:20]:
            plats = json.loads(t.get("platforms", "[]"))
            st.markdown(f"- **{t['topic_label'][:60]}** `{t['heat_score']:.0f}` {'+'.join(plats)}")
    else:
        st.info("该日期暂无数据")
