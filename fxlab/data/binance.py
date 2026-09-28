"""Binance の公開アーカイブ(data.binance.vision)から月次ファイルを取得する。"""
from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

BASE = "https://data.binance.vision/data"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "binance"


def _get(url: str) -> bytes | None:
    err = None
    for i in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:
            err = e
        time.sleep(2 ** (i + 1))
    raise RuntimeError(f"{url}: {err}")


def _csv(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        with z.open(z.namelist()[0]) as f:
            first = f.readline().decode()
    has_header = not first[:1].isdigit()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f, header=0 if has_header else None)


def url(kind: str, sym: str, y: int, m: int) -> str:
    if kind == "funding":
        return f"{BASE}/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip"
    if kind == "spot":
        return f"{BASE}/spot/monthly/klines/{sym}/1d/{sym}-1d-{y}-{m:02d}.zip"
    if kind == "perp":
        return f"{BASE}/futures/um/monthly/klines/{sym}/1d/{sym}-1d-{y}-{m:02d}.zip"
    raise ValueError(kind)


def fetch(kind: str, sym: str, y: int, m: int) -> pd.DataFrame | None:
    p = DATA_DIR / kind / sym / f"{y}-{m:02d}.parquet"
    miss = p.with_suffix(".missing")
    if p.exists():
        return pd.read_parquet(p)
    if miss.exists():
        return None
    raw = _get(url(kind, sym, y, m))
    p.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        miss.touch()
        return None
    df = _csv(raw)
    if kind == "funding":
        df.columns = ["calc_time", "interval_hours", "rate"][: len(df.columns)] if df.columns[0] != "calc_time" else df.columns
        df = df.rename(columns={"last_funding_rate": "rate", "funding_interval_hours": "interval_hours"})
        df["ts"] = pd.to_datetime(df["calc_time"], unit="ms", utc=True)
        df = df[["ts", "rate"]]
    else:
        df = df.iloc[:, :6]
        df.columns = ["open_time", "open", "high", "low", "close", "volume"]
        t = df["open_time"].astype("int64")
        t = t.where(t < 10**14, t // 1000)  # 2025 年以降の現物は μs
        df["ts"] = pd.to_datetime(t, unit="ms", utc=True)
        df = df[["ts", "open", "high", "low", "close"]]
    df.to_parquet(p, index=False)
    return df


def months(start: str, end: str):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def load(kind: str, sym: str, start: str = "2019-09", end: str = "2026-08") -> pd.DataFrame:
    parts = [fetch(kind, sym, y, m) for y, m in months(start, end)]
    parts = [p for p in parts if p is not None and len(p)]
    if not parts:
        return pd.DataFrame(columns=["ts"])
    return pd.concat(parts).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
