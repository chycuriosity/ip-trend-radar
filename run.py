"""IP Trend Radar — Main entry point."""
import sys
import os

# Add parent to path so we can import radar
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cmd_discover():
    """Run discovery: fetch hotlists + cluster + detect trends."""
    from radar.discover import run_discovery
    run_discovery()


def cmd_track(topic: str, keywords: str = "", platforms: str = ""):
    """Run deep tracking for a topic."""
    from radar.track import run_tracking
    kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [topic]
    plats = [p.strip() for p in platforms.split(",") if p.strip()] if platforms else None
    run_tracking(topic, kw, plats)


def cmd_dashboard():
    """Launch Streamlit dashboard."""
    import subprocess
    dashboard_path = os.path.join(os.path.dirname(__file__), "radar", "dashboard.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", dashboard_path])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="IP Trend Radar")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("discover", help="Run hotlist discovery")
    p_track = sub.add_parser("track", help="Deep track a topic")
    p_track.add_argument("topic", help="Topic label to track")
    p_track.add_argument("--keywords", "-k", default="", help="Search keywords (comma-separated)")
    p_track.add_argument("--platforms", "-p", default="", help="Platforms: wb,bili,zhihu,xhs (empty=all)")
    sub.add_parser("dashboard", help="Launch Streamlit dashboard")

    args = parser.parse_args()

    if args.command == "discover":
        cmd_discover()
    elif args.command == "track":
        cmd_track(args.topic, args.keywords, args.platforms)
    elif args.command == "dashboard":
        cmd_dashboard()
    else:
        parser.print_help()
