"""Gap detector: an overnight move that looks like a split NSE never announced (adr-050 step 2).

Since adr-050 every price after Trendlyne's frozen harvest is raw Bhavcopy adjusted with NSE's
corporate-actions list, and that list misses a few percent of real events (iter-200: JSWSTEEL 2017,
KARURVYSYA and CGCL 2016, HEG 2024, NAZARA, GPIL, HERITGFOOD, AJANTPHARM). A missed split reads as
a crash to signals, stops and marks. This flags the shape of one — a close-to-close move that lands
on a canonical split / bonus / consolidation ratio with no NSE event of any kind near it — so a
person looks. It NEVER adjusts a price: a real 50% crash and an unannounced 1:1 bonus look the
same from the tape alone, and guessing wrong in either direction silently corrupts history.

Ratios below 1.5 are left out on purpose. A 1:4 bonus (x1.25) or 1:5 (x1.2) is indistinguishable
from a 20% circuit move, and the iter-200 measurement found exactly those false "splits" in the
app's own detector (repeated 1.25 steps on BIRLAMONEY and KITEX were circuit moves).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from . import corp_actions
from . import trendlyne_store as ts

# Price falls by these on a split (old/new face value) or bonus ((a+b)/b): 1:1 = 2, 2:1 = 3, 1:2 = 1.5.
CANONICAL = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 20.0)
# ...and rises by these on a consolidation (1/ratio).
CONSOLIDATION = (0.5, 0.25, 0.2, 0.1)
TOL = 0.02            # within 2% of a canonical ratio
NEAR_SESSIONS = 3     # an NSE event within this many sessions of the move explains it


def _match(r: float) -> float | None:
    for c in CANONICAL + CONSOLIDATION:
        if abs(r / c - 1.0) <= TOL:
            return c
    return None


def scan(symbols, sessions: int = 5, today: dt.date | None = None) -> list[dict]:
    """Moves in the last `sessions` sessions that land on a canonical ratio with no NSE event near
    them. One dict per suspect: symbol, date, prev_close, close, ratio, canonical."""
    syms = sorted({s.upper() for s in symbols})
    if not syms:
        return []
    today = today or dt.date.today()
    start = (today - dt.timedelta(days=sessions * 3 + 20)).isoformat()
    raw = ts.raw_close_panel(syms, start=start)
    if raw.empty:
        return []
    events: dict[str, list[pd.Timestamp]] = {}
    for sym, exd, _ratio, _kind, _subj in corp_actions._rows(raw.columns, "1=1"):
        events.setdefault(sym, []).append(pd.Timestamp(exd))
    cal = raw.index
    recent = set(cal[-sessions:])
    out = []
    for sym in raw.columns:
        s = raw[sym].dropna()
        if len(s) < 2:
            continue
        r = (s.shift(1) / s).dropna()
        for day, ratio in r.items():
            if day not in recent:
                continue
            canon = _match(float(ratio))
            if canon is None:
                continue
            pos = cal.get_loc(day)
            lo = cal[max(0, pos - NEAR_SESSIONS)]
            # Within NEAR_SESSIONS sessions either side. Near the end of the tape the later sessions
            # have not happened yet, so an event up to that many sessions (~a week) ahead still counts.
            hi = (cal[pos + NEAR_SESSIONS] if pos + NEAR_SESSIONS < len(cal)
                  else cal[-1] + pd.Timedelta(days=(pos + NEAR_SESSIONS - len(cal) + 1) * 7 // 5 + 2))
            if any(lo <= e <= hi for e in events.get(sym, [])):
                continue
            out.append({"symbol": sym, "date": str(day.date()),
                        "prev_close": float(s.shift(1)[day]), "close": float(s[day]),
                        "ratio": round(float(ratio), 4), "canonical": canon})
    return sorted(out, key=lambda x: (x["date"], x["symbol"]))
