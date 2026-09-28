"""事前登録 008〜014(docs/prereg/008-014-batch.md)の判定。

既定では開発期間だけ。--unseal で、開発に合格した仮説を番号順に封印期間で評価する。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from statistics import NormalDist

import holidays

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.calendar_jp import gotobi_dates, is_jp_business_day  # noqa: E402
from fxlab.data.exness import load_m1  # noqa: E402
from fxlab.events import Prices, Trade, by_year, evaluate, local_ts, split, tstat  # noqa: E402

DEV = ("2019-01-01", "2024-01-01")
HOLDOUT = ("2024-01-01", "2100-01-01")
K0 = 1  # 002 で 1 回開けている
SLIP = 0.2
START, END = dt.date(2019, 1, 1), dt.date(2026, 8, 31)
PIPS = {"USDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01, "AUDJPY": 0.01, "EURUSD": 0.0001}


def days():
    return [START + dt.timedelta(days=i) for i in range((END - START).days + 1)]


def weekdays_excluding(hol):
    return [d for d in days() if d.weekday() < 5 and d not in hol]


def gotobi_fade(_p):
    tz = "Asia/Tokyo"
    return [Trade(d, -1, local_ts(d, 9, 55, tz), local_ts(d, 11, 0, tz)) for d in sorted(gotobi_dates(START, END))]


def session(side, tz, t_in, t_out, bdays):
    return lambda _p: [Trade(d, side, local_ts(d, *t_in, tz), local_ts(d, *t_out, tz)) for d in bdays]


YEARS = range(START.year, END.year + 1)
JP = [d for d in days() if is_jp_business_day(d)]
US = weekdays_excluding(holidays.US(years=YEARS))
UK = weekdays_excluding(holidays.UK(years=YEARS))

HYPS = {
    "008": ("EURJPY", gotobi_fade),
    "009": ("GBPJPY", gotobi_fade),
    "010": ("AUDJPY", gotobi_fade),
    "011": ("USDJPY", session(+1, "Asia/Tokyo", (9, 0), (15, 0), JP)),
    "012": ("USDJPY", session(-1, "America/New_York", (8, 0), (16, 0), US)),
    "013": ("EURUSD", session(-1, "Europe/London", (8, 0), (13, 0), UK)),
    "014": ("EURUSD", session(+1, "America/New_York", (8, 0), (16, 0), US)),
}


def line(df):
    return (f"n={len(df):4d} net={df.net.mean():+6.2f}pips (t={tstat(df.net):+5.2f}) "
            f"raw={df.raw.mean():+6.2f} win={100 * (df.net > 0).mean():4.1f}%")


def years(y):
    return ", ".join(f"{yy}:{r['mean']:+.2f}(n={int(r['count'])})" for yy, r in y.iterrows())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true")
    a = ap.parse_args()
    cache: dict[str, Prices] = {}
    k = K0
    for key, (sym, gen) in HYPS.items():
        p = cache.setdefault(sym, Prices(load_m1(sym)))
        allt = evaluate(p, gen(p), PIPS[sym], SLIP)
        dev = split(allt, *DEV)
        y = by_year(dev)
        ok = dev.net.mean() > 0 and tstat(dev.net) >= 2.0 and int((y["mean"] > 0).sum()) >= 4
        print(f"\n[{key} {sym}] 開発 {line(dev)}\n   年別: {years(y)}\n   判定(開発): {'合格' if ok else '不合格'}")
        if not ok or not a.unseal:
            continue
        k += 1
        thr = NormalDist().inv_cdf(1 - 0.05 / k)
        ho = split(allt, *HOLDOUT)
        yh = by_year(ho)
        okh = (ho.net.mean() > 0 and tstat(ho.net) >= thr
               and yh.loc[2024, "mean"] > 0 and yh.loc[2025, "mean"] > 0)
        print(f"   封印(K={k}, 必要 t≥{thr:.2f}) {line(ho)}\n   年別: {years(yh)}\n"
              f"   判定(封印): {'合格' if okh else '不合格'}")


if __name__ == "__main__":
    main()
