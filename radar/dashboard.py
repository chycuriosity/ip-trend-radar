"""Streamlit dashboard for IP Trend Radar."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.storage import get_recent_topics, get_topic_history, get_tracked_content, get_daily_summary
from radar.analyze import analyze_propagation, detect_burst, generate_ai_summary, generate_daily_report

TZ = timezone(timedelta(hours=8))

st.set_page_config(page_title="IP Trend Radar", page_icon="", layout="wide")
st.title("IP Trend Radar — 全网热点追踪")


def load_topics():
    topics = get_recent_topics(hours=24)
    return topics


def page_home():
    """Home: today's hot topics radar."""
    st.header("今日热点雷达")
    st.caption(f"更新于 {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}")

    topics = load_topics()

    if not topics:
        st.info("暂无数据，请先运行 `python -m radar.discover` 采集热榜")
        return

    # Summary metrics
    new_count = sum(1 for t in topics if t["is_new"])
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("检测到热点话题", len(topics))
    col2.metric("新出现话题", new_count)
    col3.metric("平均热度", f"{sum(t['heat_score'] for t in topics) / max(len(topics), 1):.0f}")
    col4.metric("跨平台话题", sum(1 for t in topics if len(json.loads(t.get("platforms", "[]"))) >= 3))

    st.divider()

    # Topic list
    st.subheader("热点排行")
    sorted_topics = sorted(topics, key=lambda t: t["heat_score"], reverse=True)

    for i, t in enumerate(sorted_topics[:30]):
        platforms = json.loads(t.get("platforms", "[]"))
        platform_tags = " ".join([f"`{p}`" for p in platforms])
        new_badge = " **NEW**" if t["is_new"] else ""
        heat_bar = "█" * max(1, int(t["heat_score"] / 5))

        col1, col2, col3 = st.columns([6, 2, 1])
        with col1:
            st.markdown(f"**{i+1}. {t['topic_label'][:60]}**{new_badge}")
            st.caption(f"{platform_tags} | {t['item_count']} 条内容")
        with col2:
            st.markdown(f"`{t['heat_score']:.1f}` {heat_bar}")
        with col3:
            if st.button("详情", key=f"detail_{t['id']}"):
                st.session_state["selected_topic"] = t["topic_label"]
                st.rerun()


def page_topic_detail():
    """Topic detail: deep analysis for a selected topic."""
    topic = st.session_state.get("selected_topic", "")

    if not topic:
        st.info("请从首页「热点排行」选择一个话题查看详情")
        return

    st.header(f"{topic} — 深度分析")

    # Propagation path
    st.subheader("传播链路")
    prop = analyze_propagation(topic)

    if prop["propagation_path"]:
        # Sankey-like timeline
        platforms = [p["platform"] for p in prop["propagation_path"]]
        delays = [p["delay"] for p in prop["propagation_path"]]

        cols = st.columns(len(platforms))
        for i, (p, d) in enumerate(zip(platforms, delays)):
            cols[i].metric(p, d)
            if i < len(platforms) - 1:
                cols[i].caption("→")
    else:
        st.warning("暂无传播链路数据")

    st.divider()

    # Content ranking
    st.subheader("热门内容")
    items = get_tracked_content(topic)
    if items:
        df = pd.DataFrame(items)
        display_cols = ["platform", "title", "author_name", "likes", "comments", "shares"]
        available = [c for c in display_cols if c in df.columns]
        df_display = df[available].sort_values("likes", ascending=False).head(20)
        st.dataframe(df_display, use_container_width=True)

        # Platform breakdown
        st.subheader("平台互动分布")
        platform_stats = df.groupby("platform").agg(
            内容数=("content_id", "count"),
            总点赞=("likes", "sum"),
            总评论=("comments", "sum"),
        ).reset_index()
        col1, col2 = st.columns(2)
        with col1:
            fig = px.pie(platform_stats, values="内容数", names="platform", title="内容分布")
            st.plotly_chart(fig)
        with col2:
            fig = px.bar(platform_stats, x="platform", y=["总点赞", "总评论"], title="互动分布", barmode="group")
            st.plotly_chart(fig)
    else:
        st.warning("暂无内容数据，请先运行深度追踪")

    st.divider()

    # Burst detection
    st.subheader("热度异常检测")
    burst = detect_burst(topic)
    if burst["is_burst"]:
        st.error(f"**{burst['message']}**")
    else:
        st.success(f"{burst['message']}")

    # Trend chart
    st.subheader("热度趋势")
    history = get_topic_history(topic, days=7)
    if len(history) >= 2:
        df_hist = pd.DataFrame(history)
        df_hist["time"] = pd.to_datetime(df_hist["fetch_time"])
        fig = px.line(df_hist, x="time", y="heat_score", title=f"{topic} 7日热度趋势", markers=True)
        st.plotly_chart(fig)
    else:
        st.info("数据不足，需要更多历史数据才能绘制趋势图")

    st.divider()

    # AI Summary
    st.subheader("AI 分析简报")
    with st.spinner("生成中..."):
        summary = generate_ai_summary(topic)
    st.markdown(summary)


def page_report():
    """Daily/weekly report page."""
    st.header("每日热点报告")

    date = st.date_input("选择日期", value=datetime.now(TZ).date())
    date_str = date.strftime("%Y-%m-%d")

    report = generate_daily_report()
    summary = get_daily_summary(date_str)

    col1, col2, col3 = st.columns(3)
    col1.metric("热点话题数", summary["topic_count"])
    col2.metric("热榜条目数", summary["hotlist_count"])
    col3.metric("新兴信号", len(report.get("new_signals", [])))

    st.divider()

    if report.get("new_signals"):
        st.subheader("值得关注的新兴信号")
        for t in report["new_signals"]:
            st.markdown(f"- **{t['topic_label']}** (热度: {t['heat_score']:.1f})")

    st.divider()
    st.subheader("平台热源贡献")
    contributions = report.get("platform_contributions", {})
    if contributions:
        fig = px.bar(x=list(contributions.keys()), y=list(contributions.values()),
                     title="各平台热点贡献数", labels={"x": "平台", "y": "热点数"})
        st.plotly_chart(fig)


# Navigation
pages = {
    "热点雷达": page_home,
    "话题详情": page_topic_detail,
    "每日报告": page_report,
}

# Init DB
from radar.storage import init_db
init_db()

# Sidebar
st.sidebar.title("导航")
selection = st.sidebar.radio("", list(pages.keys()))

if not st.session_state.get("selected_topic"):
    st.session_state["selected_topic"] = ""

pages[selection]()


def main():
    """Entry point for `radar-dashboard`."""
    import subprocess
    subprocess.run([sys.executable, "-m", "streamlit", "run", __file__])


if __name__ == "__main__":
    main()
