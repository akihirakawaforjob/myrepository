"""事前登録 001(docs/prereg/001-gotobi.md)の判定。

既定では開発期間だけを評価する。封印期間は --unseal を付けたときだけ評価する。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.calendar_jp import gotobi_dates, is_jp_business_day  # noqa: E402
from fxlab.data.exness import load_m1  # noqa: E402

PIP = 0.01
SLIP = 0.2  # pips, 片道
DEV = ("2019-01-01", "2024-01-01")
HOLDOUT = ("2024-01-01", "2100-01-01")
JST = dt.timedelta(hours=9)


def at(m1: pd.DataFrame, d: dt.date, hh: int, mm: int, col: str) -> float:
    ts = pd.Timestamp(dt.datetime.combine(d, dt.time(hh, mm)) - JST, tz="UTC")
    try:
        return float(m1.at[ts, col])
    except KeyError:
        return np.nan


def trades(m1: pd.DataFrame, days, t_in, t_out, side: int) -> pd.DataFrame:
    """side=+1 買い / -1 売り。net はコスト込み、raw は mid の値動き(pips)。"""
    rows = []
    for d in sorted(days):
        if side > 0:
            e, x = at(m1, d, *t_in, "ask_open"), at(m1, d, *t_out, "bid_open")
        else:
            e, x = at(m1, d, *t_in, "bid_open"), at(m1, d, *t_out, "ask_open")
        me = (at(m1, d, *t_in, "ask_open") + at(m1, d, *t_in, "bid_open")) / 2
        mx = (at(m1, d, *t_out, "ask_open") + at(m1, d, *t_out, "bid_open")) / 2
        if np.isnan([e, x, me, mx]).any():
            continue
        rows.append({"date": d, "net": side * (x - e) / PIP - 2 * SLIP, "raw": side * (mx - me) / PIP})
    return pd.DataFrame(rows)


def tstat(x: pd.Series) -> float:
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 1 else np.nan


def welch_t(a: pd.Series, b: pd.Series) -> float:
    return float((a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))


def summarize(name: str, df: pd.DataFrame) -> None:
    print(f"  {name:<28} n={len(df):4d}  net={df.net.mean():+6.2f}pips (t={tstat(df.net):+5.2f})  "
          f"raw={df.raw.mean():+6.2f}  win={100 * (df.net > 0).mean():4.1f}%")


def evaluate(m1: pd.DataFrame, start: str, end: str, label: str) -> dict:
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end) - dt.timedelta(days=1)
    gdays = gotobi_dates(s, e)
    alldays = [s + dt.timedelta(days=i) for i in range((e - s).days + 1)]
    ctrl = [d for d in alldays if is_jp_business_day(d) and d not in gdays]

    h1 = trades(m1, gdays, (8, 0), (9, 55), +1)
    h1b = trades(m1, gdays, (9, 55), (11, 0), -1)
    c = trades(m1, ctrl, (8, 0), (9, 55), +1)

    print(f"\n[{label}] {start} 〜 {end}")
    summarize("H1 五十日 08:00→09:55 買い", h1)
    summarize("H1b 五十日 09:55→11:00 売り", h1b)
    summarize("対照 非五十日 08:00→09:55 買い", c)
    diff_t = welch_t(h1.raw, c.raw)
    print(f"  五十日−対照(raw)差 = {h1.raw.mean() - c.raw.mean():+.2f} pips (t={diff_t:+.2f})")
    by_year = h1.groupby(pd.to_datetime(h1.date).dt.year).net.agg(["count", "mean"])
    print("  年別 H1 net:", ", ".join(f"{y}:{r['mean']:+.2f}(n={int(r['count'])})" for y, r in by_year.iterrows()))
    return {"h1": h1, "t": tstat(h1.net), "diff_t": diff_t, "years_pos": int((by_year["mean"] > 0).sum()),
            "years": len(by_year)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unseal", action="store_true", help="封印期間も評価する(1 回だけ)")
    a = ap.parse_args()
    m1 = load_m1("USDJPY")

    r = evaluate(m1, *DEV, "開発")
    c1 = r["h1"].net.mean() > 0 and r["t"] >= 2.0
    c2 = r["diff_t"] >= 2.0
    c3 = r["years_pos"] >= 4
    print(f"\n判定(開発): 基準1={'OK' if c1 else 'NG'} 基準2={'OK' if c2 else 'NG'} "
          f"基準3={'OK' if c3 else 'NG'} ({r['years_pos']}/{r['years']} 年)")
    if not (c1 and c2 and c3):
        print("→ 不合格。封印期間は開けない。")
        return
    if not a.unseal:
        print("→ 開発は合格。封印期間の評価には --unseal を付けて実行する。")
        return
    h = evaluate(m1, *HOLDOUT, "封印")
    ok = h["h1"].net.mean() > 0 and h["t"] >= 1.65
    print(f"\n判定(封印): 基準4={'OK' if ok else 'NG'}")


if __name__ == "__main__":
    main()
