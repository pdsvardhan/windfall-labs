"""Transitive resolution of ticker-rename chains (iter-172, to-do #246).

`rename_map` is built in scripts/gen_dead_list.py by ISIN: a dead symbol maps to the most recent
symbol sharing its ISIN. That is one hop, and one hop is not always the end of the story. A company
can rename under ISIN A and then rename again under ISIN B, at which point the ISIN join cannot see
past the intermediate:

    TATAMTRDVR --(IN9155A01020)--> TATAMOTORS --(INE155A01022)--> TMPV

TATAMOTORS is not in Trendlyne's live list (it demerged), so the row dead-ends with
`live_in_tl = False` and every consumer that asks "what is TATAMTRDVR called now?" gets an answer it
cannot use. Following the chain to TMPV - which IS live - answers the question.

Measured 2026-09-07 against the real table: 127 rows, 21 dead-ends, and exactly ONE genuine
multi-hop chain (the Tata one above). The blast radius is small; the correctness is not. The engine
itself is unaffected - it resolves renames through Bhavcopy ISIN aliases (adr-025), and TATAMOTORS
and TMPV already share INE155A01022 there. This is for rename_map's own consumers: the dead-name
survivorship backfills (#89) and the pit_mcap/adtv hole-filling (#92).
"""
from __future__ import annotations


def resolve_rename_chains(rows, live_syms) -> list[dict]:
    """Follow each row's successor through the map until it reaches a terminal symbol.

    `rows` is an iterable of (old_sym, isin, live_sym, live_in_tl); `live_syms` is the set of
    symbols Trendlyne currently lists. Returns one dict per input row with `live_sym` pointing at
    the end of the chain, `live_in_tl` recomputed against it, and `resolved_via` recording the
    intermediate hops - never an empty rewrite, so a consumer can always see what happened.

    Cycles are terminated, not followed: A->B->A resolves to the last symbol reached before the
    repeat, and is reported in `resolved_via`. A chain is a data artefact, not a guarantee, so the
    one thing this must never do is loop.
    """
    rows = [tuple(r) for r in rows]
    successor = {str(old).upper(): str(live).upper()
                 for old, _isin, live, _flag in rows if old and live}
    live = {str(s).upper() for s in live_syms}

    out: list[dict] = []
    for old, isin, first_hop, _flag in rows:
        old_u = str(old).upper()
        current = str(first_hop).upper() if first_hop else None
        hops: list[str] = []
        seen = {old_u}
        while current and current in successor and current not in seen:
            seen.add(current)
            hops.append(current)
            current = successor[current]
        # `current` is now either terminal, or the symbol that closed a cycle.
        out.append({
            "old_sym": old,
            "isin": isin,
            "live_sym": current,
            "live_in_tl": bool(current in live) if current else False,
            # Only the INTERMEDIATE symbols, in order. Empty for the common single-hop row, so a
            # non-empty value is exactly the signal "this row was followed further than the ISIN
            # join could see".
            "resolved_via": ">".join(hops) if hops else "",
        })
    return out
