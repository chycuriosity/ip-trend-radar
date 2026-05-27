"""Streamlit dashboard for IP Trend Radar."""
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
from dotenv import load_dotenv; load_dotenv()

from radar.storage import (get_recent_topics, get_topic_history, get_tracked_content,
                           get_daily_summary, init_db, DB_PATH)
from radar.analyze import (analyze_propagation, detect_burst, generate_ai_summary,
                           generate_daily_report)

TZ = timezone(timedelta(hours=8))
REPO = "chycuriosity/ip-trend-radar"

st.set_page_config(page_title="IP Trend Radar", page_icon="", layout="wide")

# ---- Background tracking poll ----
if "track_pid" in st.session_state:
    import subprocess as _sp
    out_dir = Path(st.session_state["track_output"])
    done_file = out_dir / "DONE"
    log_file = out_dir / "track.log"

    if done_file.exists():
        result = done_file.read_text().strip()
        elapsed = time.time() - st.session_state["track_start"]
        if result.startswith("ERROR"):
            st.warning(f"Tracking failed: {result} ({elapsed:.0f}s)")
        else:
            count = int(result) if result.isdigit() else 0
            load_topics.clear()
            st.success(f"Tracking complete: {count} items in {elapsed:.0f}s. Select 'Topic Detail' in nav.")
            st.session_state["sel_topic"] = st.session_state["track_topic"]
        del st.session_state["track_pid"]
        del st.session_state["track_topic"]
        del st.session_state["track_output"]
        del st.session_state["track_start"]
        time.sleep(1)
        st.rerun()
    else:
        elapsed = time.time() - st.session_state["track_start"]
        log_tail = ""
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8", errors="replace").split("\n")
            for line in reversed(lines[-5:]):
                if line.strip() and ("searching" in line.lower() or "OK:" in line or "crawler" in line.lower()):
                    log_tail = line.strip()[:120]
                    break

        st.info(f"Tracking in background ({elapsed:.0f}s elapsed). {log_tail}")
        time.sleep(3)
        st.rerun()

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


def run_track_local(topic: str, keywords: str):
    """Launch tracking in a background subprocess, poll for completion."""
    kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [topic]
    kw_str = ",".join(kw)

    # Build command to run tracking as standalone script
    script = Path(__file__).parent / "track_runner.py"
    python = sys.executable
    output_dir = Path("data") / "tracking" / topic.replace("/", "_")
    output_dir.mkdir(parents=True, exist_ok=True)
    done_file = output_dir / "DONE"
    log_file = output_dir / "track.log"

    cmd = [
        python, str(script),
        "--topic", topic,
        "--keywords", kw_str,
        "--output-dir", str(output_dir),
    ]

    import subprocess
    # Start background process
    with open(log_file, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT)

    st.session_state["track_pid"] = proc.pid
    st.session_state["track_topic"] = topic
    st.session_state["track_output"] = str(output_dir)
    st.session_state["track_start"] = time.time()
    st.info(f"Tracking started in background (PID: {proc.pid}). This page will auto-refresh.")


def run_discover():
    status = st.empty()
    status.info("Scanning hotlists...")
    try:
        from radar.discover import run_discovery as rd
        progress = st.progress(0, "Fetching...")
        topics = rd()
        progress.progress(100, "Done!")
        progress.empty()
        load_topics.clear()
        status.success(f"Found {len(topics)} topics")
        return topics
    except Exception as e:
        status.error(f"Failed: {e}")
        return []


# ---- Sidebar ----
st.sidebar.title("Controls")

st.sidebar.subheader("Data")
c1, c2 = st.sidebar.columns(2)
if c1.button("Refresh", use_container_width=True):
    load_topics.clear()
    if download_latest_data():
        st.success("Updated")
        st.rerun()
    else:
        st.warning("No new data")

if c2.button("Discover", use_container_width=True, type="primary"):
    run_discover()
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("Deep Track")
st.sidebar.caption("Local Chrome, ~10 min for 4 platforms")
tt = st.sidebar.text_input("Topic", placeholder="e.g. topic name", key="tt_inp")
tk = st.sidebar.text_input("Keywords", placeholder="comma separated", key="tk_inp")
if st.sidebar.button("Start Tracking", use_container_width=True, type="primary"):
    if tt:
        run_track_local(tt, tk or tt)
        st.rerun()
    else:
        st.sidebar.warning("Enter topic name")

st.sidebar.divider()
st.sidebar.caption(f"Repo: {REPO}")
db_mtime = Path(DB_PATH).stat().st_mtime if Path(DB_PATH).exists() else 0
if db_mtime:
    t = datetime.fromtimestamp(db_mtime, TZ).strftime("%m-%d %H:%M")
    st.sidebar.caption(f"Data: {t}")

# ---- Navigation ----
pages = {"Trend Radar": "home", "Topic Detail": "detail", "Daily Report": "report"}
page = st.sidebar.radio("Nav", list(pages.keys()), label_visibility="collapsed")

# ---- Home ----
if pages[page] == "home":
    st.title("IP Trend Radar")
    st.header("Today's Hot Topics")
    st.caption(f"Updated {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')} | Auto-refresh every 2h")

    topics = load_topics()
    if not topics:
        st.warning("No data - click 'Discover' in sidebar or 'Refresh' to download")
    else:
        new_count = sum(1 for t in topics if t["is_new"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Topics", len(topics))
        c2.metric("New", new_count)
        c3.metric("Avg Heat", f"{sum(t['heat_score'] for t in topics) / max(len(topics), 1):.0f}")
        c4.metric("Platforms 3+", sum(1 for t in topics if len(json.loads(t.get("platforms", "[]"))) >= 3))

        st.divider()
        st.subheader("Top Topics")

        sorted_topics = sorted(topics, key=lambda t: t["heat_score"], reverse=True)
        for i, t in enumerate(sorted_topics[:30]):
            platforms = json.loads(t.get("platforms", "[]"))
            tags = " ".join([f"`{p}`" for p in platforms])
            new_badge = " **NEW**" if t["is_new"] else ""
            heat_bar = chr(9608) * max(1, int(t["heat_score"] / 5))

            c1, c2, c3 = st.columns([5, 2, 1])
            with c1:
                st.markdown(f"**{i+1}. {t['topic_label'][:60]}**{new_badge}")
                st.caption(f"{tags} | {t['item_count']} items")
            with c2:
                st.markdown(f"`{t['heat_score']:.0f}` {heat_bar}")
            with c3:
                if st.button("Detail", key=f"dt_{t['id']}"):
                    st.session_state["sel_topic"] = t["topic_label"]
                    st.rerun()

        st.divider()
        st.subheader("Platform Distribution")
        plat_count = {}
        for t in topics:
            for p in json.loads(t.get("platforms", "[]")):
                plat_count[p] = plat_count.get(p, 0) + 1
        if plat_count:
            fig = px.bar(x=list(plat_count.keys()), y=list(plat_count.values()),
                         title="Hot Topics per Platform", labels={"x": "Platform", "y": "Count"})
            st.plotly_chart(fig, use_container_width=True)

# ---- Detail ----
elif pages[page] == "detail":
    topic = st.session_state.get("sel_topic", "")
    if not topic:
        st.info("Click 'Detail' on a topic from the home page")
    else:
        st.title(f"{topic}")

        items = get_tracked_content(topic)

        if not items:
            st.warning("Not tracked yet")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Track This Topic", type="primary", use_container_width=True):
                    run_track_local(topic, topic)
                    st.rerun()
            with c2:
                if st.button("Back to Home", use_container_width=True):
                    st.rerun()
        else:
            st.info(f"{len(items)} items tracked")

        prop = analyze_propagation(topic)
        if prop["propagation_path"]:
            st.subheader("Propagation Path")
            cols = st.columns(len(prop["propagation_path"]))
            for i, step in enumerate(prop["propagation_path"]):
                cols[i].metric(step["platform"], step["delay"])
            if prop["origin_platform"]:
                st.caption(f"Origin: {prop['origin_platform']}")

        if items:
            st.divider()
            st.subheader("Top Content")
            df = pd.DataFrame(items)
            dis_cols = ["platform", "title", "author_name", "likes", "comments", "shares"]
            st.dataframe(df[[c for c in dis_cols if c in df.columns]].head(20), use_container_width=True)

            stats = df.groupby("platform").agg(count=("content_id", "count"), likes=("likes", "sum")).reset_index()
            c1, c2 = st.columns(2)
            with c1:
                fig = px.pie(stats, values="count", names="platform", title="Content by Platform")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                fig = px.bar(df.head(20), x="title", y="likes", title="Content Engagement")
                st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Trend")
        hist = get_topic_history(topic, days=7)
        if len(hist) >= 2:
            df_h = pd.DataFrame(hist)
            df_h["time"] = pd.to_datetime(df_h["fetch_time"])
            fig = px.line(df_h, x="time", y="heat_score", title="7-Day Trend", markers=True)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("More data needed for trend chart")

        burst = detect_burst(topic)
        if burst.get("is_burst"):
            st.error(f"Anomaly: {burst['message']}")
        else:
            st.info(f"Anomaly: {burst.get('message', 'insufficient data')}")

        st.divider()
        st.subheader("AI Summary")
        with st.spinner("Generating..."):
            st.markdown(generate_ai_summary(topic))

# ---- Report ----
elif pages[page] == "report":
    st.title("Daily Report")
    date = st.date_input("Date", datetime.now(TZ).date())
    summary = get_daily_summary(date.strftime("%Y-%m-%d"))

    c1, c2, c3 = st.columns(3)
    c1.metric("Topics", summary["topic_count"])
    c2.metric("Hotlist Items", summary["hotlist_count"])
    c3.metric("Date", summary["date"])

    if summary["topics"]:
        st.divider()
        st.subheader(f"Topics for {summary['date']}")
        for t in summary["topics"][:20]:
            plats = json.loads(t.get("platforms", "[]"))
            st.markdown(f"- **{t['topic_label'][:60]}** `{t['heat_score']:.0f}` {'+'.join(plats)}")
    else:
        st.info("No data for this date")
