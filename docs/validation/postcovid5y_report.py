"""Render the robustness verdict table from /tmp/robust5y_results.jsonl."""

import json

rows = [json.loads(l) for l in open("/tmp/robust5y_results.jsonl")]
by = {}
for r in rows:
    sid = r["sid"]
    wtag = r["tag"].split("/", 1)[1]
    by.setdefault(sid, {})[wtag] = r

errs = [r for r in rows if "error" in r]
print("errors:", len(errs), [r["tag"] for r in errs][:8])

print("\nPER-FINALIST PROTOCOL RESULTS")
hdr = ("{:<18} {:>7} {:>6} {:>7} | {:>6} {:>6} | {:>7} {:>6} | {:>5} | {:>10}"
       .format("strategy", "5y", "sh", "dd", "H1", "H2", "pre", "presh",
               "seg+", "corr dd"))
print(hdr)
for sid, w in by.items():
    f = w.get("5y", {})
    if "error" in f or f.get("cagr") is None:
        print(f"{sid:<18} 5y RUN FAILED")
        continue
    segs = [s for s in (f.get("segments") or []) if s is not None]
    bsegs = f.get("bench_segments") or []
    beat = sum(1 for s, b in zip(f.get("segments") or [], bsegs)
               if s is not None and b is not None and s > b)
    pos = sum(1 for s in segs if s > 0)
    corr = f.get("correction") or {}
    h1 = w.get("H1", {}).get("cagr")
    h2 = w.get("H2", {}).get("cagr")
    pre = w.get("pre", {}).get("cagr")
    presh = w.get("pre", {}).get("sharpe")

    def pct(x):
        return "{:.1%}".format(x) if x is not None else "n/a"

    print("{:<18} {:>7} {:>6} {:>7} | {:>6} {:>6} | {:>7} {:>6} | {:>2}/{:<2} | {:>7} {}"
          .format(sid, pct(f["cagr"]), "{:.2f}".format(f["sharpe"]),
                  pct(f["maxdd"]), pct(h1), pct(h2), pct(pre),
                  "{:.2f}".format(presh) if presh is not None else "n/a",
                  beat, len(segs), pct(corr.get("depth")),
                  (corr.get("recovered") or "not-rec")[:10]))

print("\nSEGMENT DETAIL (half-year returns, strategy vs benchmark)")
labels = ["21H2", "22H1", "22H2", "23H1", "23H2", "24H1", "24H2", "25H1", "25H2", "26H1"]
for sid, w in by.items():
    f = w.get("5y", {})
    segs = f.get("segments")
    if not segs:
        continue
    cells = []
    for lab, s, b in zip(labels, segs, f.get("bench_segments") or [None] * 10):
        mark = "?" if s is None else ("+" if (b is not None and s > b) else ("o" if s > 0 else "-"))
        cells.append(f"{lab}:{mark}")
    print("  {:<18} {}".format(sid, " ".join(cells)))
print("  (+ beat benchmark · o positive but lagged · - negative · ? no data)")

print("\nREGIME GATE ON 5Y WINDOW")
for sid, w in by.items():
    f, g1, g2 = w.get("5y", {}), w.get("5y_ma100", {}), w.get("5y_ma150", {})
    if not g1 and not g2:
        continue

    def trip(r):
        if not r or r.get("cagr") is None:
            return "failed"
        return "{:.1%}/{:.2f}/{:.1%}".format(r["cagr"], r["sharpe"], r["maxdd"])

    print("  {:<18} off {}   ma100 {}   ma150 {}".format(
        sid, trip(f), trip(g1), trip(g2)))
