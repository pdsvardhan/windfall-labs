"""Merge the warm-slice rankings with the fresh gap-fill runs; print combined 5y ranking."""

import json

gap = [json.loads(l) for l in open("/tmp/gap5y_results.jsonl")]
sliced = json.load(open("/tmp/slice5y_rows.json"))

errs = [g for g in gap if "error" in g]
print("errors:", len(errs), [e["sid"] for e in errs][:5])

print("\nVALIDATION (cold-start fresh vs warm slice):")
sl = {m["sid"]: m for m in sliced}
for g in gap:
    if g["kind"] == "validate" and "error" not in g:
        s = sl.get(g["sid"], {})
        print("  {:<18} fresh {:.1%}/{:.2f}/{:.1%}   slice {:.1%}/{:.2f}/{:.1%}".format(
            g["sid"], g["cagr"], g["sharpe"], g["maxdd"],
            s.get("cagr", 0), s.get("sharpe", 0), s.get("maxdd", 0)))

rows = [{"sid": m["sid"], "cagr": m["cagr"], "sharpe": m["sharpe"],
         "maxdd": m["maxdd"], "src": "slice"} for m in sliced]
for g in gap:
    if g["kind"] == "gapfill" and "error" not in g and g.get("cagr") is not None:
        rows.append({"sid": g["sid"], "cagr": g["cagr"], "sharpe": g["sharpe"],
                     "maxdd": g["maxdd"], "src": "fresh"})
print("\n{} total in combined ranking".format(len(rows)))

print("\nCOMBINED TOP 20 BY 5Y CAGR")
for i, m in enumerate(sorted(rows, key=lambda x: -x["cagr"])[:20], 1):
    print("{:>3}. {:<24} {:>7.1%}  sh {:>5.2f}  dd {:>7.1%}  [{}]".format(
        i, m["sid"], m["cagr"], m["sharpe"], m["maxdd"], m["src"]))

print("\nCOMBINED TOP 12 BY 5Y SHARPE")
for i, m in enumerate(sorted(rows, key=lambda x: -x["sharpe"])[:12], 1):
    print("{:>3}. {:<24} {:>7.1%}  sh {:>5.2f}  dd {:>7.1%}  [{}]".format(
        i, m["sid"], m["cagr"], m["sharpe"], m["maxdd"], m["src"]))

fams = {}
for m in rows:
    fams.setdefault(m["sid"].split("_")[0], []).append(m["cagr"])
print("\nFAMILY MEDIANS (complete)")
for f, cs in sorted(fams.items(), key=lambda kv: -sorted(kv[1])[len(kv[1]) // 2]):
    cs.sort()
    print("  {:<6} median {:>7.1%}  best {:>7.1%}  n={}".format(
        f, cs[len(cs) // 2], cs[-1], len(cs)))

json.dump(rows, open("/tmp/combined5y.json", "w"))
