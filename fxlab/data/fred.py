"""FRED(米セントルイス連銀)の公開 CSV を取得してキャッシュする。"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "fred"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"


def load(series_id: str, refresh: bool = False) -> pd.Series:
    p = DATA_DIR / f"{series_id}.csv"
    if refresh or not p.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL.format(id=series_id), timeout=60) as r:
            p.write_bytes(r.read())
    df = pd.read_csv(p)
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    s.name = series_id
    return s.dropna()
