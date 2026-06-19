"""Tests for ASM/GSM surveillance flags (iter-25)."""
from windfall.data import surveillance
from windfall.data.surveillance import normalize


def test_normalize_flattens_asm_longterm_shortterm_and_gsm():
    asm = {
        "longterm": {"data": [{"symbol": "AAA", "isin": "INE1", "asmSurvIndicator": "Stage I",
                               "survCode": "LTASM-I", "survDesc": "d", "asmTime": "19-Jun-2026"}]},
        "shortterm": {"data": [{"symbol": "BBB", "asmSurvIndicator": "Stage II",
                                "asmTime": "19-Jun-2026"}]},
    }
    gsm = [{"symbol": "CCC", "gsmStage": "LXII", "gsmTime": "19-Jun-2026", "survDesc": "x"},
           {"symbol": None}]                         # missing symbol must be dropped
    rows = normalize(asm, gsm)
    assert {r["symbol"]: r["list_type"] for r in rows} == {"AAA": "ASM-LT", "BBB": "ASM-ST", "CCC": "GSM"}
    aaa = next(r for r in rows if r["symbol"] == "AAA")
    assert aaa["stage"] == "Stage I" and aaa["isin"] == "INE1"


def test_ingest_latest_flags_and_signal_annotation():
    surveillance.ingest(rows=[
        {"symbol": "AAA", "isin": "INE1", "list_type": "ASM-LT", "stage": "Stage I",
         "surv_code": "c", "surv_desc": "d", "as_of": "x"},
        {"symbol": "CCC", "isin": "INE3", "list_type": "GSM", "stage": "LXII",
         "surv_code": "c", "surv_desc": "d", "as_of": "x"},
    ], fetch_date="2026-06-19")

    lf = surveillance.latest_flags()
    assert lf["fetch_date"] == "2026-06-19"
    assert "AAA" in lf["flags"] and "CCC" in lf["flags"]

    out = surveillance.annotate_signals({
        "signals": [{"ticker": "AAA.NS", "action": "buy"}, {"ticker": "ZZZ.NS", "action": "buy"}],
        "warnings": [],
    })
    sigs = {s["ticker"]: s for s in out["signals"]}
    assert "ASM-LT" in sigs["AAA.NS"]["surveillance"]      # surveilled name tagged
    assert "surveillance" not in sigs["ZZZ.NS"]            # clean name untouched
    assert any("surveillance" in w for w in out["warnings"])  # buy-into-surveilled warning raised
