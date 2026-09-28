"""事前登録 002(docs/prereg/002-gotobi-fade.md)の判定。封印期間だけを評価する。"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fxlab.calendar_jp import gotobi_dates  # noqa: E402
from fxlab.data.exness import load_m1  # noqa: E402
from test_gotobi import HOLDOUT, summarize, trades, tstat  # noqa: E402


def main() -> None:
    m1 = load_m1("USDJPY")
    s = dt.date.fromisoformat(HOLDOUT[0])
    e = m1.index.max().date()
    df = trades(m1, gotobi_dates(s, e), (9, 55), (11, 0), -1)
    print(f"[封印] {s} 〜 {e}")
    summarize("002 五十日 09:55→11:00 売り", df)
    by_year = df.groupby(pd.to_datetime(df.date).dt.year).net.agg(["count", "mean"])
    print("  年別 net:", ", ".join(f"{y}:{r['mean']:+.2f}(n={int(r['count'])})" for y, r in by_year.iterrows()))
    c1 = df.net.mean() > 0 and tstat(df.net) >= 1.96
    c2 = by_year.loc[2024, "mean"] > 0 and by_year.loc[2025, "mean"] > 0
    print(f"\n判定: 基準1={'OK' if c1 else 'NG'} 基準2={'OK' if c2 else 'NG'} → {'合格' if c1 and c2 else '不合格'}")


if __name__ == "__main__":
    main()
