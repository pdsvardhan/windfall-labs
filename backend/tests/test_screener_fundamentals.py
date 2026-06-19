"""screener.in historical-fundamentals ingester — regression tests for iter-6 bug fixes.

Covers the pure, network-free cores of the three fixes:
  - ROCE no longer crashes when capital employed (equity + borrowings) is exactly 0 (VAML class).
  - the sparse-consolidated -> standalone basis-selection rule (ABB class).
The IDEA direct-symbol-first resolution + corrupt-row cleanup is verified end-to-end by re-ingest,
not here (it needs the live screener page).
"""
from windfall.data.screener_fundamentals import build_records, _prefer_standalone


def _parsed(equity_capital, reserves, borrow, *, sales=100.0, op=10.0, pbt=5.0,
            net=4.0, interest=1.0):
    """Minimal one-period (Mar 2025) parsed company dict."""
    p = "Mar 2025"
    return {
        "profit-loss": {
            "Sales": {p: sales}, "Operating Profit": {p: op},
            "Profit before tax": {p: pbt}, "Net Profit": {p: net},
            "Interest": {p: interest}, "Expenses": {p: sales - op},
        },
        "balance-sheet": {
            "Equity Capital": {p: equity_capital}, "Reserves": {p: reserves},
            "Borrowings": {p: borrow}, "Total Assets": {p: 200.0},
        },
        "cash-flow": {"Cash from Operating Activity": {p: 8.0}},
    }


def test_roce_zero_capital_employed_does_not_crash():
    # VAML Mar-2025 shape: equity = -0.04, borrowings = +0.04 -> cap employed = 0.0
    recs = build_records("VAML.NS", _parsed(equity_capital=-0.04, reserves=0.0, borrow=0.04),
                         "standalone")
    assert len(recs) == 1
    r = recs[0]
    assert r["roce"] is None                 # zero denominator -> None, not ZeroDivisionError
    assert r["roe"] is not None              # equity != 0, so ROE still computes
    assert r["equity"] == -0.04 and r["borrowings"] == 0.04


def test_roce_negative_capital_employed_is_none():
    # VAML Mar-2026 shape: equity = -0.07, borrowings = +0.06 -> cap employed = -0.01.
    # ROCE is undefined on a non-positive base; must be None, not a fabricated ~300%.
    recs = build_records("VAML.NS", _parsed(equity_capital=-0.07, reserves=0.0, borrow=0.06),
                         "standalone")
    assert recs[0]["roce"] is None


def test_roce_computes_when_capital_employed_nonzero():
    recs = build_records("AAA.NS", _parsed(equity_capital=40.0, reserves=60.0, borrow=50.0),
                         "consolidated")
    r = recs[0]
    # ebit = pbt + interest = 5 + 1 = 6; cap employed = equity(100) + borrow(50) = 150
    assert r["roce"] is not None
    assert abs(r["roce"] - (6 / 150 * 100)) < 1e-9


def test_prefer_standalone_rule():
    assert _prefer_standalone(4, 12) is True        # ABB: sparse consolidated, richer standalone
    assert _prefer_standalone(0, 12) is True        # empty consolidated (ABBOTINDIA class)
    assert _prefer_standalone(11, 12) is False      # healthy consolidated stays put
    assert _prefer_standalone(3, 3) is False         # young IPO: equal counts, no switch
    assert _prefer_standalone(5, 4) is False         # standalone not richer -> keep consolidated
    assert _prefer_standalone(6, 12) is False        # at threshold (not < 6) -> keep consolidated
