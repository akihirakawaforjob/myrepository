"""Exness の公開ティックアーカイブを取得して Parquet に保存する。

ティック(実際の Bid/Ask)と、そこから作る 1 分足(Bid/Ask 別 OHLC + スプレッド統計)を
月単位で保存する。時刻はすべて UTC。
"""
from __future__ import annotations

import io
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

BASE_URL = "https://ticks.ex2archive.com/ticks/{sym}/{y}/{m:02d}/Exness_{sym}_{y}_{m:02d}.zip"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def tick_path(sym: str, y: int, m: int) -> Path:
    return DATA_DIR / "ticks" / sym / f"{y}-{m:02d}.parquet"


def m1_path(sym: str, y: int, m: int) -> Path:
    return DATA_DIR / "m1" / sym / f"{y}-{m:02d}.parquet"


def _download(url: str, retries: int = 4) -> bytes | None:
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # ネットワーク断は指数バックオフで再試行
            err = e
        time.sleep(2 ** (i + 1))
    raise RuntimeError(f"download failed: {url}: {err}")


def load_ticks_csv(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        with z.open(name) as f:
            df = pd.read_csv(f, usecols=["Timestamp", "Bid", "Ask"], dtype={"Bid": "float64", "Ask": "float64"})
    df["ts"] = pd.to_datetime(df["Timestamp"], utc=True, format="ISO8601")
    df = df.drop(columns="Timestamp").rename(columns={"Bid": "bid", "Ask": "ask"})
    df = df.sort_values("ts", kind="stable").reset_index(drop=True)
    return df[["ts", "bid", "ask"]]


def ticks_to_m1(t: pd.DataFrame) -> pd.DataFrame:
    g = t.set_index("ts").resample("1min", label="left", closed="left")
    bid = g["bid"].ohlc().add_prefix("bid_")
    ask = g["ask"].ohlc().add_prefix("ask_")
    spread = (t["ask"] - t["bid"]).set_axis(t["ts"]).resample("1min")
    out = pd.concat([bid, ask], axis=1)
    out["spread_mean"] = spread.mean()
    out["spread_max"] = spread.max()
    out["ticks"] = g["bid"].count()
    return out[out["ticks"] > 0].astype({"ticks": "int32"})


def fetch_month(sym: str, y: int, m: int, keep_ticks: bool = True) -> str:
    mp = m1_path(sym, y, m)
    if mp.exists() and (not keep_ticks or tick_path(sym, y, m).exists()):
        return "cached"
    raw = _download(BASE_URL.format(sym=sym, y=y, m=m))
    if raw is None:
        return "missing"
    t = load_ticks_csv(raw)
    if keep_ticks:
        tp = tick_path(sym, y, m)
        tp.parent.mkdir(parents=True, exist_ok=True)
        t.to_parquet(tp, index=False, compression="zstd")
    mp.parent.mkdir(parents=True, exist_ok=True)
    ticks_to_m1(t).to_parquet(mp, compression="zstd")
    return f"ok ({len(t):,} ticks)"


def load_m1(sym: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    files = sorted((DATA_DIR / "m1" / sym).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no m1 data for {sym}; run scripts/fetch_exness.py")
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index < pd.Timestamp(end, tz="UTC")]
    return df
