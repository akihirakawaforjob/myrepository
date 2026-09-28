"""使い方: python scripts/fetch_exness.py USDJPY AUDJPY --start 2019-01 --end 2026-08"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.data.exness import fetch_month  # noqa: E402


def months(start: str, end: str):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--start", default="2019-01")
    ap.add_argument("--end", default="2026-08")
    ap.add_argument("--no-ticks", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    jobs = [(s, y, m) for s in a.symbols for y, m in months(a.start, a.end)]

    def run(job):
        s, y, m = job
        try:
            r = fetch_month(s, y, m, keep_ticks=not a.no_ticks)
        except Exception as e:  # 1 か月の失敗で全体を止めない
            r = f"ERROR {e}"
        print(f"{s} {y}-{m:02d} {r}", flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(run, jobs))


if __name__ == "__main__":
    main()
