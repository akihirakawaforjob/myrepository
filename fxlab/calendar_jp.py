"""日本の営業日と五十日。"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import holidays

GOTOBI_DAYS = (5, 10, 15, 20, 25, 30)


@lru_cache(maxsize=None)
def _jp_holidays(year: int) -> frozenset[dt.date]:
    return frozenset(holidays.Japan(years=year))


def is_jp_business_day(d: dt.date) -> bool:
    if d.weekday() >= 5 or d in _jp_holidays(d.year):
        return False
    if (d.month, d.day) in {(12, 31), (1, 1), (1, 2), (1, 3)}:  # 銀行休業日
        return False
    return True


def prev_business_day(d: dt.date) -> dt.date:
    while not is_jp_business_day(d):
        d -= dt.timedelta(days=1)
    return d


def last_business_day(year: int, month: int) -> dt.date:
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    return prev_business_day(nxt - dt.timedelta(days=1))


def gotobi_dates(start: dt.date, end: dt.date) -> set[dt.date]:
    """start 以上 end 以下の五十日(繰り上げ後)。"""
    out: set[dt.date] = set()
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        for day in GOTOBI_DAYS:
            try:
                out.add(prev_business_day(dt.date(y, m, day)))
            except ValueError:  # 2 月 30 日など
                pass
        out.add(last_business_day(y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return {d for d in out if start <= d <= end}
