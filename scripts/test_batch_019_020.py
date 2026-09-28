"""事前登録 019〜020(docs/prereg/019-020-batch.md)の判定。FRED の日足、損益は bp。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.data.fred import load  # noqa: E402

COST_BPS = 5.0
MARKUP = 2.5  # %/年
HOLDOUT_START = "2010-01-01"
K0 = 2


def jp_rate() -> pd.Series:
    call = load("IRSTCI01JPM156N")
    disc = load("INTDSRJPM193N")
    return pd.concat([disc[disc.index < call.index.min()], call]).sort_index()


def tom_trades(px: pd.Series, rate: pd.Series) -> pd.DataFrame:
    """最終取引日の 1 つ前の終値で買い、翌月の第 3 取引日の終値で売る。rate は年率 %。"""
    idx = px.index
    rate = rate.reindex(idx.union(rate.index)).ffill().reindex(idx)
    rows = []
    for i in range(1, len(idx) - 3):
        if idx[i].month != idx[i + 1].month:  # i が月の最終取引日
            e, x = i - 1, i + 3
            days = (idx[x] - idx[e]).days
            r = rate.iloc[e]
            if np.isnan(r):
                continue
            raw = (px.iloc[x] / px.iloc[e] - 1) * 1e4
            carry = (max(r, 0) + MARKUP) / 100 * days / 365 * 1e4
            rows.append({"date": idx[e], "raw": raw, "net": raw - COST_BPS - carry})
    return pd.DataFrame(rows)


def tstat(x):
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def line(df):
    return f"n={len(df):4d} net={df.net.mean():+7.2f}bp (t={tstat(df.net):+5.2f}) raw={df.raw.mean():+7.2f} win={100 * (df.net > 0).mean():4.1f}%"


HYPS = {
    "019": ("NIKKEI225", jp_rate, "1950-01-01", 4),
    "020": ("NASDAQCOM", lambda: load("DTB3"), "1971-02-05", 3),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true")
    a = ap.parse_args()
    k = K0
    for key, (sid, ratef, dev_start, need_decades) in HYPS.items():
        df = tom_trades(load(sid), ratef())
        dev = df[(df.date >= dev_start) & (df.date < HOLDOUT_START)]
        dec = dev.groupby(dev.date.dt.year // 10 * 10).net.agg(["count", "mean"])
        ok = dev.net.mean() > 0 and tstat(dev.net) >= 2.0 and int((dec["mean"] > 0).sum()) >= need_decades
        print(f"\n[{key} {sid}] 開発 {line(dev)}")
        print("   年代別:", ", ".join(f"{y}s:{r['mean']:+.1f}(n={int(r['count'])})" for y, r in dec.iterrows()))
        print(f"   判定(開発): {'合格' if ok else '不合格'}")
        if not ok or not a.unseal:
            continue
        k += 1
        thr = NormalDist().inv_cdf(1 - 0.05 / k)
        ho = df[df.date >= HOLDOUT_START]
        h1, h2 = ho[ho.date < "2018-01-01"], ho[ho.date >= "2018-01-01"]
        okh = ho.net.mean() > 0 and tstat(ho.net) >= thr and h1.net.mean() > 0 and h2.net.mean() > 0
        print(f"   封印(K={k}, 必要 t≥{thr:.2f}) {line(ho)}")
        print(f"   前半 2010-17: {h1.net.mean():+.1f}(n={len(h1)}), 後半 2018-: {h2.net.mean():+.1f}(n={len(h2)})")
        print(f"   判定(封印): {'合格' if okh else '不合格'}")


if __name__ == "__main__":
    main()
