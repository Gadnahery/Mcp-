"""Replay the strategy engine over saved OHLC history (same engine as Telegram /replay).

Usage: python replay.py history.json
history.json: {"symbol": "...", "m15": [...], "m5": [...], "m1": [...]}
The downloader also fetches 1M candles for outcome resolution and executable-fill estimates.
Get history with: python scripts/fetch_history.py SYMBOL START END history.json
"""
import json
import sys

from monitoring.replay_engine import format_replay_report, run_replay


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    data = json.load(open(sys.argv[1]))
    result = run_replay(data.get("symbol", "?"), data["m15"], data["m5"], m1=data.get("m1"), warmup=60)
    print(format_replay_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
