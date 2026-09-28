"""使い方: python scripts/fetch_binance.py BTC ETH ... (2020-01〜2026-08 のファンディング・現物・先物日足)"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.data.binance import fetch, months  # noqa: E402

jobs = [(k, c + "USDT", y, m) for c in sys.argv[1:] for k in ("funding", "spot", "perp")
        for y, m in months("2020-01", "2026-08")]


def run(j):
    try:
        d = fetch(*j)
        return None if d is not None else f"missing {j}"
    except Exception as e:
        return f"ERROR {j} {e}"


with ThreadPoolExecutor(8) as ex:
    for r in ex.map(run, jobs):
        if r:
            print(r, flush=True)
print("done", len(jobs))
