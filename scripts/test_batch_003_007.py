"""事前登録 003〜007(docs/prereg/003-007-batch.md)の判定。

既定では開発期間だけ。--unseal で、開発に合格した仮説だけ封印期間を評価する。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import holidays
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.calendar_jp import gotobi_dates, is_jp_business_day  # noqa: E402
from fxlab.data.exness import load_m1  # noqa: E402
from fxlab.events import Prices, Trade, by_year, evaluate, local_ts, split, tstat  # noqa: E402

DEV = ("2019-01-01", "2024-01-01")
HOLDOUT = ("2024-01-01", "2100-01-01")
HOLDOUT_T = 2.45
PIP = 0.01
START, END = dt.date(2019, 1, 1), dt.date(2026, 8, 31)


def days(start=START, end=END):
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def uk_business_days():
    uk = holidays.UK(years=range(START.year, END.year + 1))
    return [d for d in days() if d.weekday() < 5 and d not in uk]


def h003(p: Prices):
    g = gotobi_dates(START, END)
    tz = "Asia/Tokyo"
    return [Trade(d, -1, local_ts(d, 9, 55, tz), local_ts(d, 11, 0, tz))
            for d in days() if is_jp_business_day(d) and d not in g]


def london_fix(p: Prices, month_end_only: bool):
    tz = "Europe/London"
    bdays = uk_business_days()
    if month_end_only:
        last = {}
        for d in bdays:
            last[(d.year, d.month)] = d
        bdays = sorted(last.values())
    out = []
    for d in bdays:
        dmove = p.mid_at(local_ts(d, 16, 0, tz)) - p.mid_at(local_ts(d, 15, 0, tz))
        if np.isnan(dmove) or dmove == 0:
            continue
        out.append(Trade(d, -int(np.sign(dmove)), local_ts(d, 16, 1, tz), local_ts(d, 17, 0, tz)))
    return out


def surprise(p: Prices, tz: str, t0, t1, t_exit):
    """t0→t1 の 5 分の値動きが直前 20 営業日の中央値の 3 倍を超えた日に順張り。"""
    hist, out = [], []
    for d in days():
        if d.weekday() >= 5:
            continue
        m = p.mid_at(local_ts(d, *t1, tz)) - p.mid_at(local_ts(d, *t0, tz))
        if np.isnan(m):
            continue
        if len(hist) >= 20:
            thr = 3 * np.median(np.abs(hist[-20:]))
            if abs(m) > thr and m != 0:
                out.append(Trade(d, int(np.sign(m)), local_ts(d, *t1, tz), local_ts(d, *t_exit, tz)))
        hist.append(m)
    return out


HYPS = {
    "003": ("USDJPY", 0.2, h003),
    "004": ("USDJPY", 0.2, lambda p: london_fix(p, True)),
    "005": ("USDJPY", 0.2, lambda p: london_fix(p, False)),
    "006": ("USDJPY", 0.5, lambda p: surprise(p, "America/New_York", (8, 30), (8, 35), (10, 0))),
    "007": ("AUDJPY", 0.5, lambda p: surprise(p, "Australia/Sydney", (11, 30), (11, 35), (13, 0))),
}


def line(name, df):
    return (f"{name}: n={len(df):4d} net={df.net.mean():+6.2f}pips (t={tstat(df.net):+5.2f}) "
            f"raw={df.raw.mean():+6.2f} win={100 * (df.net > 0).mean():4.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true")
    a = ap.parse_args()
    prices = {s: Prices(load_m1(s)) for s in {"USDJPY", "AUDJPY"}}
    for k, (sym, slip, gen) in HYPS.items():
        p = prices[sym]
        allt = evaluate(p, gen(p), PIP, slip)
        dev = split(allt, *DEV)
        y = by_year(dev)
        ok1 = dev.net.mean() > 0 and tstat(dev.net) >= 2.0
        ok2 = int((y["mean"] > 0).sum()) >= 4
        print(f"\n[{k} {sym}] 開発 " + line("", dev))
        print("   年別:", ", ".join(f"{yy}:{r['mean']:+.2f}(n={int(r['count'])})" for yy, r in y.iterrows()))
        verdict = "合格" if ok1 and ok2 else "不合格"
        print(f"   判定(開発): 基準1={'OK' if ok1 else 'NG'} 基準2={'OK' if ok2 else 'NG'} → {verdict}")
        if not (ok1 and ok2) or not a.unseal:
            continue
        ho = split(allt, *HOLDOUT)
        yh = by_year(ho)
        okh = (ho.net.mean() > 0 and tstat(ho.net) >= HOLDOUT_T
               and yh.loc[2024, "mean"] > 0 and yh.loc[2025, "mean"] > 0)
        print(f"   封印 " + line("", ho))
        print("   年別:", ", ".join(f"{yy}:{r['mean']:+.2f}(n={int(r['count'])})" for yy, r in yh.iterrows()))
        print(f"   判定(封印): {'合格' if okh else '不合格'}")


if __name__ == "__main__":
    main()
