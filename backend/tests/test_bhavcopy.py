"""Unit tests for the Bhavcopy ingester's pure logic (no network)."""
import datetime as dt

import pandas as pd

from scripts.bhavcopy_ingest import (UDIFF_START, legacy_url, normalize_legacy,
                                      normalize_udiff, udiff_url)


def test_url_builders_match_nse_layout():
    assert udiff_url(dt.date(2026, 6, 18)).endswith(
        "/content/cm/BhavCopy_NSE_CM_0_0_0_20260618_F_0000.csv.zip")
    assert legacy_url(dt.date(2020, 1, 2)).endswith(
        "/historical/EQUITIES/2020/JAN/cm02JAN2020bhav.csv.zip")


def test_format_switch_boundary():
    assert dt.date(2024, 7, 8) >= UDIFF_START      # UDiFF on/after the switch
    assert dt.date(2024, 7, 7) < UDIFF_START       # legacy before it


def test_normalize_udiff_filters_series_and_drops_null_close():
    df = pd.DataFrame({
        "SctySrs": ["EQ", "GB", "EQ"],                      # GB (bond) must be filtered out
        "TckrSymb": ["RELIANCE", "SOMEBOND", "NULLCLOSE"],
        "ISIN": ["INE002A01018", "X", "INE999A01010"],
        "OpnPric": [1330.0, 100.0, 5.0], "HghPric": [1333.9, 100.0, 5.0],
        "LwPric": [1322.0, 100.0, 5.0], "ClsPric": [1328.1, 100.0, None],  # last row: null close
        "LastPric": [1328.1, 100.0, 5.0], "PrvsClsgPric": [1332.7, 100.0, 5.0],
        "TtlTradgVol": [15494549, 10, 0], "TtlTrfVal": [2e10, 1000, 0],
        "TtlNbOfTxsExctd": [210055, 1, 0],
    })
    out = normalize_udiff(df, dt.date(2026, 6, 18))
    assert list(out["ticker"]) == ["RELIANCE.NS"]          # bond dropped + null-close dropped
    r = out.iloc[0]
    assert r["isin"] == "INE002A01018" and r["series"] == "EQ"
    assert abs(r["close"] - 1328.1) < 1e-6 and r["volume"] == 15494549


def test_normalize_legacy_maps_columns():
    df = pd.DataFrame({
        "SYMBOL": ["TCS"], "SERIES": ["EQ"], "OPEN": [3000.0], "HIGH": [3050.0],
        "LOW": [2990.0], "CLOSE": [3020.0], "LAST": [3020.0], "PREVCLOSE": [2995.0],
        "TOTTRDQTY": [1_000_000], "TOTTRDVAL": [3e9], "TIMESTAMP": ["02-JAN-2020"],
        "TOTALTRADES": [50000], "ISIN": ["INE467B01029"],
    })
    out = normalize_legacy(df, dt.date(2020, 1, 2))
    r = out.iloc[0]
    assert r["ticker"] == "TCS.NS" and r["isin"] == "INE467B01029"
    assert abs(r["close"] - 3020.0) < 1e-6 and str(r["date"]) == "2020-01-02"


def test_normalize_legacy_tolerates_missing_totaltrades():
    df = pd.DataFrame({
        "SYMBOL": ["INFY"], "SERIES": ["EQ"], "OPEN": [1.0], "HIGH": [1.0], "LOW": [1.0],
        "CLOSE": [1.0], "LAST": [1.0], "PREVCLOSE": [1.0], "TOTTRDQTY": [1], "TOTTRDVAL": [1.0],
        "ISIN": ["INE009A01021"],                          # no TOTALTRADES column
    })
    out = normalize_legacy(df, dt.date(2015, 1, 1))
    assert len(out) == 1 and pd.isna(out.iloc[0]["n_trades"])
