"""FRED の系列から月次の超過リターンを作る(事前登録 021〜022)。

r_t は t−1 月末 → t 月末のリターン。金利は t−1 月末の値を使う(期初に分かっている値)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from fxlab.data.fred import load

RATE_IDS = {
    "US": ["DTB3"],
    "JP": ["IR3TIB01JPM156N", "IRSTCI01JPM156N", "INTDSRJPM193N"],
    "AU": ["IR3TIB01AUM156N", "IRSTCI01AUM156N"],
    "GB": ["IR3TIB01GBM156N", "IRSTCI01GBM156N"],
    "CA": ["IR3TIB01CAM156N", "IRSTCI01CAM156N"],
    "CH": ["IR3TIB01CHM156N", "IRSTCI01CHM156N"],
    "NZ": ["IR3TIB01NZM156N", "IRSTCI01NZM156N"],
    "SE": ["IR3TIB01SEM156N", "IRSTCI01SEM156N"],
    "NO": ["IR3TIB01NOM156N", "IRSTCI01NOM156N"],
    "EZ": ["IR3TIB01EZM156N", "IRSTCI01EZM156N"],
    "DE": ["IR3TIB01DEM156N", "IRSTCI01DEM156N"],
}

# 通貨: (FRED id, True なら 1 USD あたりの外貨なので逆数を取る, 金利の国)
FX = {
    "JPY": ("DEXJPUS", True, "JP"),
    "AUD": ("DEXUSAL", False, "AU"),
    "GBP": ("DEXUSUK", False, "GB"),
    "CAD": ("DEXCAUS", True, "CA"),
    "CHF": ("DEXSZUS", True, "CH"),
    "NZD": ("DEXUSNZ", False, "NZ"),
    "SEK": ("DEXSDUS", True, "SE"),
    "NOK": ("DEXNOUS", True, "NO"),
    "EUR": ("DEXUSEU", False, "EZ"),
}
EQUITY = {"NIKKEI": ("NIKKEI225", "JP"), "NASDAQ": ("NASDAQCOM", "US")}
# 独・英・日の 10 年債(IRLTLT01xxM156N)は OECD の月平均値で、リターンを滑らかにして
# トレンドを水増しするため使わない(修正記録 2)。
BONDS = {
    "UST10": ("DGS10", "US"),
}


def month_end(s: pd.Series, cutoff: str | None) -> pd.Series:
    if cutoff:
        s = s[s.index <= pd.Timestamp(cutoff)]
    m = s.resample("ME").last()
    return m


def short_rate(country: str, cutoff: str | None) -> pd.Series:
    """優先順に、その月に値がある系列を使う。無い月は直近 3 か月以内で埋める。"""
    parts = [month_end(load(i), cutoff) for i in RATE_IDS[country]]
    idx = parts[0].index
    for p in parts[1:]:
        idx = idx.union(p.index)
    # 系列が途中で終わっても 3 か月は埋められるよう、暦の上の全月に広げてから埋める
    last = pd.Timestamp(cutoff) if cutoff else pd.Timestamp.today()
    idx = pd.date_range(idx.min(), last, freq="ME")
    out = pd.Series(np.nan, index=idx)
    for p in reversed(parts):  # 優先度の高いものが最後に上書きする
        p = p.reindex(idx)
        out = out.where(p.isna(), p)
    return out.ffill(limit=3)


def excess_returns(cutoff: str | None = None) -> pd.DataFrame:
    """列 = 資産、行 = 月末。値 = その月の超過リターン(小数)。"""
    rates = {c: short_rate(c, cutoff) for c in RATE_IDS}
    us = rates["US"]
    cols = {}
    for name, (sid, invert, ctry) in FX.items():
        s = month_end(load(sid), cutoff)
        if invert:
            s = 1.0 / s
        diff = (rates[ctry] - us).reindex(s.index)
        cols[name] = s / s.shift(1) - 1 + diff.shift(1) / 1200
    for name, (sid, ctry) in EQUITY.items():
        p = month_end(load(sid), cutoff)
        cols[name] = p / p.shift(1) - 1 - rates[ctry].reindex(p.index).shift(1) / 1200
    for name, (sid, ctry) in BONDS.items():
        y = month_end(load(sid), cutoff) / 100
        dur = ((1 - (1 + y / 2) ** -20) / y).where(y != 0, 10.0)  # y→0 の極限は 10
        cols[name] = y.shift(1) / 12 - dur.shift(1) * (y - y.shift(1)) - rates[ctry].reindex(y.index).shift(1) / 1200
    return pd.DataFrame(cols).sort_index()


def fx_rates(cutoff: str | None = None) -> pd.DataFrame:
    """キャリー用: 列 = 通貨(USD を含む)、値 = 短期金利(年率 %)。"""
    cols = {c: short_rate(ctry, cutoff) for c, (_, _, ctry) in FX.items()}
    cols["USD"] = short_rate("US", cutoff)
    return pd.DataFrame(cols).sort_index()


def fx_spot_available(cutoff: str | None = None) -> pd.DataFrame:
    return pd.DataFrame({c: month_end(load(sid), cutoff).notna() for c, (sid, _, _) in FX.items()})


TC, HOLD = 0.0005, 0.01  # 売買 5bp/持ち高の変化量、保有 1%/年


def tsmom(r: pd.DataFrame, target: float = 0.10, cap: float = 5.0) -> pd.Series:
    """021: 各月末 t の情報で t+1 月の持ち高を決め、t+1 月のリターンを返す(index は t+1 月末)。"""
    months = r.index
    prev_w = pd.Series(0.0, index=r.columns)
    out = {}
    for k in range(len(months) - 1):
        hist = r.iloc[: k + 1]  # t までの情報だけ
        nxt = r.iloc[k + 1]
        rets = []
        new_w = pd.Series(0.0, index=r.columns)
        for a in r.columns:
            last12 = hist[a].iloc[-12:]
            last36 = hist[a].iloc[-36:].dropna()
            if len(last12) < 12 or last12.isna().any() or len(last36) < 24 or np.isnan(nxt[a]):
                continue
            s = np.sign(np.prod(1 + last12.values) - 1)
            sigma = last36.std(ddof=1) * np.sqrt(12)
            if s == 0 or sigma <= 0:
                continue
            w = float(np.clip(s * target / sigma, -cap, cap))
            new_w[a] = w
            rets.append(w * nxt[a] - TC * abs(w - prev_w[a]) - HOLD / 12 * abs(w))
        prev_w = new_w
        if rets:
            out[months[k + 1]] = float(np.mean(rets))
    return pd.Series(out, name="tsmom")


def carry(r: pd.DataFrame, rates: pd.DataFrame, spot_ok: pd.DataFrame, n: int = 3) -> pd.Series:
    """022: 月末 t の金利で上位 n 通貨を買い下位 n 通貨を売る。t+1 月のリターン。"""
    months = r.index
    ccys = list(rates.columns)  # USD を含む 10 通貨
    prev_w = pd.Series(0.0, index=ccys)
    out = {}
    for k in range(len(months) - 1):
        t, t1 = months[k], months[k + 1]
        avail = []
        for c in ccys:
            rt = rates.at[t, c] if t in rates.index else np.nan
            if np.isnan(rt):
                continue
            if c != "USD":
                ok = spot_ok.at[t, c] if t in spot_ok.index else False
                if not ok or np.isnan(r.at[t1, c]):
                    continue
            avail.append((c, rt))
        if len(avail) < 6:
            prev_w = pd.Series(0.0, index=ccys)
            continue
        avail.sort(key=lambda x: (-x[1], x[0]))
        w = pd.Series(0.0, index=ccys)
        for c, _ in avail[:n]:
            w[c] += 1 / n
        for c, _ in avail[-n:]:
            w[c] -= 1 / n
        ret = sum(w[c] * r.at[t1, c] for c in ccys if c != "USD" and w[c] != 0)
        # USD の持ち高は USD 建てでは何も取引しないのでコストはかからない
        cost = sum(TC * abs(w[c] - prev_w[c]) + HOLD / 12 * abs(w[c]) for c in ccys if c != "USD")
        out[t1] = ret - cost
        prev_w = w
    return pd.Series(out, name="carry")
