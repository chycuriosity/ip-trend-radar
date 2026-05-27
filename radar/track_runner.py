"""Standalone tracking script - called as subprocess from dashboard."""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from radar.track import run_tracking

parser = argparse.ArgumentParser()
parser.add_argument("--topic", required=True)
parser.add_argument("--keywords", required=True)
parser.add_argument("--output-dir", required=True)
args = parser.parse_args()

kw = [k.strip() for k in args.keywords.split(",") if k.strip()]

# Create DONE file when finished
done_file = os.path.join(args.output_dir, "DONE")
try:
    results = run_tracking(args.topic, kw)
    with open(done_file, "w") as f:
        f.write(str(len(results)))
    print(f"SUCCESS: {len(results)} items")
except Exception as e:
    with open(done_file, "w") as f:
        f.write(f"ERROR: {e}")
    print(f"FAILED: {e}")
