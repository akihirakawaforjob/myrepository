"""事前登録 015〜018(docs/prereg/015-018-batch.md)の判定。損益は bp。

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
from fxlab.calendar_jp import is_jp_business_day  # noqa: E402
from fxlab.data.exness import load_m1  # noqa: E402
from fxlab.events import Prices, Trade, by_year, evaluate_bps, local_ts, split, tstat  # noqa: E402
from fxlab.fomc import FOMC_ANNOUNCEMENTS  # noqa: E402

DEV = ("2020-01-01", "2024-01-01")
HOLDOUT = ("2024-01-01", "2100-01-01")
K0 = 1
SLIP_BPS, CARRY_BPS = 0.5, 2.0
START, END = dt.date(2020, 1, 1), dt.date(2026, 8, 31)
NY, TK = "America/New_York", "Asia/Tokyo"

ALL = [START + dt.timedelta(days=i) for i in range((END - START).days + 40)]  # 月初の第 3 営業日まで見る
NYSE = holidays.NYSE(years=range(START.year, END.year + 2))
US_BD = [d for d in ALL if d.weekday() < 5 and d not in NYSE]
JP_BD = [d for d in ALL if is_jp_business_day(d)]


def tom(bdays, tz, hh, mm):
    """最終営業日の 1 つ前の日に買い、翌月の第 3 営業日に売る。"""
    out = []
    for i, d in enumerate(bdays):
        if i + 1 < len(bdays) and bdays[i + 1].month != d.month:  # d は月の最終営業日
            if i >= 1 and i + 3 < len(bdays) and d <= END:
                ent, ex = bdays[i - 1], bdays[i + 3]
                out.append(Trade(ent, +1, local_ts(ent, hh, mm, tz), local_ts(ex, hh, mm, tz)))
    return out


def pre_fomc():
    out = []
    for a in FOMC_ANNOUNCEMENTS:
        if not (START < a <= END):
            continue
        prev = max(d for d in US_BD if d < a)
        out.append(Trade(prev, +1, local_ts(prev, 14, 0, NY), local_ts(a, 13, 55, NY)))
    return out


def overnight():
    bd = [d for d in US_BD if d <= END]
    return [Trade(d, +1, local_ts(d, 15, 55, NY), local_ts(n, 9, 35, NY)) for d, n in zip(bd, bd[1:])]


HYPS = {
    "015": ("US500", lambda: tom(US_BD, NY, 15, 55)),
    "016": ("JP225", lambda: tom(JP_BD, TK, 15, 0)),
    "017": ("US500", pre_fomc),
    "018": ("US500", overnight),
}


def line(df, n_planned):
    return (f"n={len(df):4d}/{n_planned} net={df.net.mean():+7.2f}bp (t={tstat(df.net):+5.2f}) "
            f"raw={df.raw.mean():+7.2f} win={100 * (df.net > 0).mean():4.1f}%")


def years(y):
    return ", ".join(f"{yy}:{r['mean']:+.1f}(n={int(r['count'])})" for yy, r in y.iterrows())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true")
    a = ap.parse_args()
    cache: dict[str, Prices] = {}
    k = K0
    for key, (sym, gen) in HYPS.items():
        p = cache.setdefault(sym, Prices(load_m1(sym)))
        planned = gen()
        allt = evaluate_bps(p, planned, SLIP_BPS, CARRY_BPS)
        n_dev_planned = sum(1 for t in planned if DEV[0] <= str(t.date) < DEV[1])
        dev = split(allt, *DEV)
        y = by_year(dev)
        ok = dev.net.mean() > 0 and tstat(dev.net) >= 2.0 and int((y["mean"] > 0).sum()) >= 3
        print(f"\n[{key} {sym}] 開発 {line(dev, n_dev_planned)}\n   年別: {years(y)}\n"
              f"   判定(開発): {'合格' if ok else '不合格'}")
        if not ok or not a.unseal:
            continue
        k += 1
        thr = NormalDist().inv_cdf(1 - 0.05 / k)
        ho = split(allt, *HOLDOUT)
        yh = by_year(ho)
        okh = (ho.net.mean() > 0 and tstat(ho.net) >= thr
               and yh.loc[2024, "mean"] > 0 and yh.loc[2025, "mean"] > 0)
        n_ho_planned = sum(1 for t in planned if str(t.date) >= HOLDOUT[0])
        print(f"   封印(K={k}, 必要 t≥{thr:.2f}) {line(ho, n_ho_planned)}\n   年別: {years(yh)}\n"
              f"   判定(封印): {'合格' if okh else '不合格'}")


if __name__ == "__main__":
    main()
