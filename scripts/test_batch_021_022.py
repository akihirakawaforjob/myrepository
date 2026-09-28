"""事前登録 021〜022(docs/prereg/021-022-batch.md)の判定。月次、FRED。

既定では 2009-12-31 でデータを切ってから計算する(封印期間は読み込み時点で存在しない)。
--unseal を付けたときだけ全期間を読み込み、開発に合格した仮説を番号順に封印期間で評価する。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.monthly import carry, excess_returns, fx_rates, fx_spot_available, tsmom  # noqa: E402

DEV = ("1973-01-01", "2010-01-01")
HOLD = ("2010-01-01", "2026-09-01")
K0 = 4
OUT = Path(__file__).resolve().parents[1] / "reports"


def tstat(x):
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def sel(s, a, b):
    return s[(s.index >= a) & (s.index < b)]


def describe(s):
    ann = s.mean() * 12
    vol = s.std(ddof=1) * np.sqrt(12)
    cum = (1 + s).cumprod()
    dd = (cum / cum.cummax() - 1).min()
    return (f"n={len(s)} ({s.index[0]:%Y-%m}〜{s.index[-1]:%Y-%m}) 平均={s.mean() * 1e4:+.1f}bp/月 "
            f"(t={tstat(s):+.2f}) 年率={ann * 100:+.2f}% 年率vol={vol * 100:.2f}% "
            f"シャープ={ann / vol:+.2f} 最大DD={dd * 100:.1f}%")


def series(cutoff):
    r = excess_returns(cutoff)
    return {"021": tsmom(r), "022": carry(r, fx_rates(cutoff), fx_spot_available(cutoff))}, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true")
    a = ap.parse_args()
    res, r = series(None if a.unseal else "2009-12-31")
    k = K0
    for key, s in res.items():
        s.to_frame("ret").rename_axis("month").to_csv(OUT / f"ret_{key}{'_all' if a.unseal else '_dev'}.csv",
                                                       date_format="%Y-%m")
        dev = sel(s, *DEV)
        dec = dev.groupby(dev.index.year // 10 * 10).mean()
        ok = dev.mean() > 0 and tstat(dev) >= 2.0 and int((dec > 0).sum()) >= 3
        print(f"\n[{key}] 開発 {describe(dev)}")
        print("   年代別(bp/月):", ", ".join(f"{d}s:{v * 1e4:+.1f}" for d, v in dec.items()))
        print(f"   判定(開発): {'合格' if ok else '不合格'}")
        if not ok or not a.unseal:
            continue
        k += 1
        thr = NormalDist().inv_cdf(1 - 0.05 / k)
        ho = sel(s, *HOLD)
        h1, h2 = sel(ho, "2010-01-01", "2018-01-01"), sel(ho, "2018-01-01", "2100-01-01")
        okh = ho.mean() > 0 and tstat(ho) >= thr and h1.mean() > 0 and h2.mean() > 0
        nas = r["NASDAQ"].reindex(ho.index)
        print(f"   封印(K={k}, 必要 t≥{thr:.2f}) {describe(ho)}")
        print(f"   前半 2010-17: {h1.mean() * 1e4:+.1f}bp, 後半 2018-: {h2.mean() * 1e4:+.1f}bp, "
              f"ナスダック超過リターンとの相関 {ho.corr(nas):+.2f}")
        print(f"   判定(封印): {'合格' if okh else '不合格'}")


if __name__ == "__main__":
    main()
