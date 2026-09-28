"""時刻で入って時刻で出る取引の評価。"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

UTC = ZoneInfo("UTC")


def local_ts(d: dt.date, hh: int, mm: int, tz: str) -> pd.Timestamp:
    return pd.Timestamp(dt.datetime.combine(d, dt.time(hh, mm), tzinfo=ZoneInfo(tz))).tz_convert(UTC)


class Prices:
    """1 分足の始値の参照。欠けている分足は NaN を返す(その取引はスキップされる)。"""

    def __init__(self, m1: pd.DataFrame):
        self.ask = m1["ask_open"].to_dict()
        self.bid = m1["bid_open"].to_dict()

    def ask_at(self, ts) -> float:
        return self.ask.get(ts, np.nan)

    def bid_at(self, ts) -> float:
        return self.bid.get(ts, np.nan)

    def mid_at(self, ts) -> float:
        return (self.ask_at(ts) + self.bid_at(ts)) / 2


@dataclass
class Trade:
    date: dt.date
    side: int  # +1 買い / -1 売り
    t_in: pd.Timestamp
    t_out: pd.Timestamp


def evaluate(p: Prices, trades: list[Trade], pip: float, slip_pips: float) -> pd.DataFrame:
    rows = []
    for t in trades:
        if t.side > 0:
            e, x = p.ask_at(t.t_in), p.bid_at(t.t_out)
        else:
            e, x = p.bid_at(t.t_in), p.ask_at(t.t_out)
        me, mx = p.mid_at(t.t_in), p.mid_at(t.t_out)
        if np.isnan([e, x, me, mx]).any():
            continue
        rows.append({"date": t.date, "side": t.side,
                     "net": t.side * (x - e) / pip - 2 * slip_pips,
                     "raw": t.side * (mx - me) / pip})
    return pd.DataFrame(rows, columns=["date", "side", "net", "raw"])


def tstat(x: pd.Series) -> float:
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 else np.nan


def split(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    d = pd.to_datetime(df["date"])
    return df[(d >= start) & (d < end)]


def by_year(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(pd.to_datetime(df["date"]).dt.year)["net"].agg(["count", "mean"])


def evaluate_bps(p: Prices, trades: list[Trade], slip_bps: float, carry_bps_per_day: float) -> pd.DataFrame:
    """損益を bp(0.01%)で測る。保有コストは暦日数 × carry_bps_per_day。"""
    rows = []
    for t in trades:
        if t.side > 0:
            e, x = p.ask_at(t.t_in), p.bid_at(t.t_out)
        else:
            e, x = p.bid_at(t.t_in), p.ask_at(t.t_out)
        me, mx = p.mid_at(t.t_in), p.mid_at(t.t_out)
        if np.isnan([e, x, me, mx]).any():
            continue
        days = (t.t_out - t.t_in).total_seconds() / 86400
        carry = carry_bps_per_day * max(1, round(days)) if days > 0.25 else 0.0
        rows.append({"date": t.date, "side": t.side,
                     "net": t.side * (x - e) / me * 1e4 - 2 * slip_bps - carry,
                     "raw": t.side * (mx - me) / me * 1e4})
    return pd.DataFrame(rows, columns=["date", "side", "net", "raw"])
