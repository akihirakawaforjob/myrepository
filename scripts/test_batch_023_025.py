"""事前登録 023〜025(docs/prereg/023-025-batch.md)の判定。

既定では 2023-12-31 でデータを切ってから計算する。--unseal で全期間を読み、開発合格分だけ封印を評価する。
日 d の損益 = (d 00:00, d+1 00:00] に確定したファンディング + (現物 − 先物)の d の日次リターン。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.data import binance  # noqa: E402
from fxlab.data.fred import load as fred  # noqa: E402

UNIVERSE = "BTC ETH BCH XRP EOS LTC TRX ETC LINK ADA XLM XMR DASH XTZ ZEC ATOM BNB ONT IOTA BAT VET NEO IOST QTUM".split()
CAP = 1.5          # 資本 / 想定元本
FEE = 0.0015       # 建て・外し 1 回あたり(現物 0.10% + 先物 0.05%)
THRESH = 0.0001    # 8 時間あたり
DEV = ("2020-01-01", "2024-01-01")
HOLD = ("2024-01-01", "2026-09-01")
K0 = 5
OUT = Path(__file__).resolve().parents[1] / "reports"


def daily(coin: str, cutoff: str | None) -> pd.DataFrame:
    """列: fund(その日に受け取るファンディング), basis(現物−先物), trail(直近 7 日の 8h 換算平均, 日の始めに既知), perp_up。"""
    sym = coin + "USDT"
    f = binance.load("funding", sym, "2020-01")
    s = binance.load("spot", sym, "2020-01")
    p = binance.load("perp", sym, "2020-01")
    if f.empty or s.empty or p.empty:
        return pd.DataFrame()
    if cutoff:
        end = pd.Timestamp(cutoff, tz="UTC") + pd.Timedelta(days=1)
        f, s, p = f[f.ts < end], s[s.ts < end], p[p.ts < end]
    # 00:00 ちょうどの確定は前日の分。確定時刻から 1 分引いた日付に入れる
    fd = f.assign(d=(f.ts - pd.Timedelta(minutes=1)).dt.floor("D")).groupby("d").rate.sum()
    sc = s.set_index(s.ts.dt.floor("D")).close.astype(float)
    pc = p.set_index(p.ts.dt.floor("D")).close.astype(float)
    ph = p.set_index(p.ts.dt.floor("D")).high.astype(float)
    df = pd.DataFrame({"spot": sc, "perp": pc, "perp_high": ph})
    df["fund"] = fd.reindex(df.index)
    df["basis"] = df.spot.pct_change(fill_method=None) - df.perp.pct_change(fill_method=None)
    df["perp_up"] = df.perp_high / df.perp.shift(1) - 1
    # 日 d の 00:00 までに確定したファンディング(= d−1 までの日次合計)の直近 7 日合計 / 21
    df["trail"] = fd.reindex(df.index).fillna(0).rolling(7, min_periods=7).sum().shift(1) / 21
    ok = df.fund.notna() & df.basis.notna()
    return df[ok]


def run_static(d: pd.DataFrame) -> pd.Series:
    """常時保有。資本比の日次リターン。最初の日と最後の日に手数料。"""
    r = (d.fund + d.basis) / CAP
    r.iloc[0] -= FEE / CAP
    r.iloc[-1] -= FEE / CAP
    return r


def run_conditional(ds: dict[str, pd.DataFrame]) -> pd.Series:
    days = sorted(set().union(*[d.index for d in ds.values()]))
    prev = {}
    out = {}
    for day in days:
        active = [c for c, d in ds.items() if day in d.index and d.at[day, "trail"] > THRESH]
        w = {c: 1 / CAP / len(active) for c in active} if active else {}
        turn = sum(abs(w.get(c, 0) - prev.get(c, 0)) for c in set(w) | set(prev))
        r = sum(w[c] * (ds[c].at[day, "fund"] + ds[c].at[day, "basis"]) for c in active)
        out[day] = r - FEE * turn
        prev = w
    return pd.Series(out)


def monthly_excess(r: pd.Series, tb: pd.Series) -> pd.Series:
    m = r.groupby(r.index.to_period("M")).sum()
    rf = tb.resample("ME").last().shift(1)
    rf.index = rf.index.to_period("M")
    return (m - rf.reindex(m.index) / 1200).dropna()


def tstat(x):
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def describe(x: pd.Series) -> str:
    return (f"n={len(x)} 平均超過={x.mean() * 1e4:+.1f}bp/月 (t={tstat(x):+.2f}) "
            f"年率超過={x.mean() * 1200:+.2f}% 年率vol={x.std(ddof=1) * np.sqrt(12) * 100:.2f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true")
    a = ap.parse_args()
    cutoff = None if a.unseal else "2023-12-31"
    tb = fred("DTB3")
    if cutoff:
        tb = tb[tb.index <= cutoff]
    ds = {c: daily(c, cutoff) for c in UNIVERSE}
    ds = {c: d for c, d in ds.items() if not d.empty}
    print("銘柄:", len(ds), " 先物の最大日次上昇率:",
          ", ".join(f"{c}:{d.perp_up.max() * 100:.0f}%" for c, d in ds.items() if d.perp_up.max() > 0.3) or "30% 超なし")
    series = {"023": run_static(ds["BTC"]), "024": run_static(ds["ETH"]), "025": run_conditional(ds)}
    k = K0
    for key, r in series.items():
        m = monthly_excess(r, tb)
        m.rename("excess").to_csv(OUT / f"ret_{key}{'_all' if a.unseal else '_dev'}.csv")
        dev = m[(m.index >= pd.Period(DEV[0][:7])) & (m.index < pd.Period(DEV[1][:7]))]
        yr = dev.groupby(dev.index.year).mean()
        ok = dev.mean() > 0 and tstat(dev) >= 2.0 and int((yr > 0).sum()) >= 3
        extra = ""
        if key == "025":
            dd = r[(r.index >= DEV[0]) & (r.index < DEV[1])]
            extra = f" 保有あり日の割合={(dd != 0).mean() * 100:.0f}%"
        neg = ""
        if key in ("023", "024"):
            c = "BTC" if key == "023" else "ETH"
            fd = ds[c].fund[(ds[c].index >= DEV[0]) & (ds[c].index < DEV[1])]
            neg = f" ファンディングが負の日={(fd < 0).mean() * 100:.0f}%"
        print(f"\n[{key}] 開発 {describe(dev)}{extra}{neg}")
        print("   年別(bp/月):", ", ".join(f"{y}:{v * 1e4:+.1f}" for y, v in yr.items()))
        print(f"   判定(開発): {'合格' if ok else '不合格'}")
        if not ok or not a.unseal:
            continue
        k += 1
        thr = NormalDist().inv_cdf(1 - 0.05 / k)
        ho = m[(m.index >= pd.Period(HOLD[0][:7])) & (m.index < pd.Period(HOLD[1][:7]))]
        yh = ho.groupby(ho.index.year).mean()
        okh = ho.mean() > 0 and tstat(ho) >= thr and yh.get(2024, -1) > 0 and yh.get(2025, -1) > 0
        print(f"   封印(K={k}, 必要 t≥{thr:.2f}) {describe(ho)}")
        print("   年別(bp/月):", ", ".join(f"{y}:{v * 1e4:+.1f}" for y, v in yh.items()))
        print(f"   判定(封印): {'合格' if okh else '不合格'}")


if __name__ == "__main__":
    main()
