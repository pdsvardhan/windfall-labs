"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { PaperPosition } from "@/lib/types";
import { money, pctSigned, num, signClass, dateShort } from "@/lib/format";
import { Card, Pill } from "@/components/ui";

// Notional capital per strategy — used to surface how much is actually deployed vs. sitting in cash
// (the ₹1L books are only partly invested when weights × ₹1L round below one share).
const NOTIONAL = 100000;

// Friendly labels for the tracked strategies (strategy_id -> shown name + one-line what).
const LABELS: Record<string, { name: string; note: string }> = {
  DVM_user: { name: "DVM (yours)", note: "mcap>500 · avg(D,V,M)≥55 · top-10 by DVM blend" },
  DVM_dm_m_20: { name: "DVM · durability+momentum", note: "top-20 · monthly" },
  BLEND_70_30: { name: "Blend 70/30", note: "70% momentum + 30% low-vol" },
  MOM_roc252_m_20: { name: "Momentum (12-mo)", note: "top-20 · monthly" },
  CMP_valmom_m_20: { name: "Value + momentum", note: "top-20 · monthly" },
};

interface Agg {
  sid: string; positions: PaperPosition[]; open: number; closed: number;
  invested: number; value: number; pnl: number; pnlPct: number; wins: number; marked: number;
}

function aggregate(sid: string, ps: PaperPosition[]): Agg {
  let invested = 0, value = 0, wins = 0, open = 0, closed = 0, marked = 0;
  for (const p of ps) {
    const cost = p.entry * p.shares;
    const mark = (p.last_price ?? p.entry) * p.shares;
    invested += cost; value += mark;
    if (p.status === "open") open++; else closed++;
    if (p.last_price != null) marked++;
    if ((p.return_pct ?? 0) > 0) wins++;
  }
  const pnl = value - invested;
  return { sid, positions: ps, open, closed, invested, value, pnl,
    pnlPct: invested ? pnl / invested : 0, wins, marked };
}

export default function PaperPage() {
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  function load() {
    api.paperPositions().then(setPositions).catch((e) => setErr(e.message));
  }
  useEffect(load, []);

  async function markNow() {
    setBusy(true); setErr(null);
    try { await api.markPaper(); load(); }
    catch (e) { setErr(`mark failed: ${(e as Error).message}`); }
    finally { setBusy(false); }
  }

  const aggs = useMemo(() => {
    const by: Record<string, PaperPosition[]> = {};
    for (const p of positions) (by[p.strategy_id ?? "unassigned"] ||= []).push(p);
    return Object.entries(by).map(([sid, ps]) => aggregate(sid, ps))
      .sort((a, b) => b.pnlPct - a.pnlPct);
  }, [positions]);

  const lastMark = useMemo(() => {
    const ds = positions.map((p) => p.last_date).filter(Boolean) as string[];
    return ds.sort().at(-1) ?? null;
  }, [positions]);

  const totalInvested = aggs.reduce((a, x) => a + x.invested, 0);
  const totalPnl = aggs.reduce((a, x) => a + x.pnl, 0);

  return (
    <div>
      <div className="flex items-end justify-between mt-6 mb-4 animate-rise">
        <div>
          <h1 className="text-[34px] font-extrabold tracking-tight">Paper trades</h1>
          <p className="text-muted text-[14px] mt-1.5 max-w-[640px]">
            A zero-risk live dry-run on real NSE end-of-day prices — no money at stake. Returns are
            <b> gross of trading costs</b> (brokerage/STT/slippage not yet deducted). Watch the
            strategies compete before funding one.
          </p>
        </div>
        <button className="btn btn-ink" disabled={busy} onClick={markNow}>{busy ? "marking…" : "↻ Mark to market"}</button>
      </div>

      {err && <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}><span className="text-loss text-[13px]">{err}</span></Card>}

      {/* honesty / freshness banner */}
      <Card className="px-4 py-3 mb-4 text-[12px] text-muted" style={{ background: "#f7f5fc" }}>
        <b className="text-ink">How this works:</b> prices are NSE Bhavcopy <b>end-of-day</b> (not intraday),
        refreshed weekday nights; P&amp;L marks to the last trading day{lastMark ? <> — currently <b className="text-ink">{lastMark}</b></> : ""}
        {" "}and is <b>gross of costs</b>. Each position enters at the close it was opened on, so day-0 P&amp;L
        starts at zero. Books are only partly invested when a name&apos;s weight rounds below one share —
        see <b>cash %</b> per strategy. Monthly rebalances need a fresh Trendlyne pull. You still place every real order yourself.
      </Card>

      {positions.length === 0 ? (
        <Card className="px-5 py-10 text-center text-[13px] text-muted">No paper positions yet.</Card>
      ) : (
        <>
          {/* portfolio total */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mb-4 text-[13px]">
            <span className="text-muted">Across {aggs.length} strategies · {positions.length} positions</span>
            <span>Deployed <b className="tn">{money(totalInvested)}</b> <span className="text-faint">of {money(aggs.length * NOTIONAL)} notional</span></span>
            <span>Total P&amp;L <b className={`tn ${signClass(totalPnl)}`}>{money(totalPnl)}</b> <span className="text-faint">gross</span></span>
          </div>

          {/* leaderboard of strategies */}
          <div className="flex flex-col gap-2.5">
            {aggs.map((a, i) => {
              const lab = LABELS[a.sid] ?? { name: a.sid, note: a.sid === "dvm-monthly" ? "older test book" : "" };
              const isOpen = open === a.sid;
              return (
                <Card key={a.sid} className="overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setOpen(isOpen ? null : a.sid)}
                    className="w-full text-left px-5 py-4 flex items-center gap-4 wf-row"
                    aria-expanded={isOpen}
                  >
                    <span className="text-[13px] font-extrabold text-faint w-5 tn">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="font-extrabold text-[15px]">{lab.name}</div>
                      <div className="text-[11.5px] text-faint truncate">{lab.note}</div>
                    </div>
                    <div className="text-right w-[92px]">
                      <div className={`font-extrabold text-[16px] tn ${signClass(a.pnl)}`}>{pctSigned(a.pnlPct)}</div>
                      <div className="text-[11px] text-faint tn">{money(a.pnl)}</div>
                    </div>
                    <div className="text-right w-[74px] hidden sm:block">
                      <div className="text-[13px] font-bold tn">{a.open}</div>
                      <div className="text-[11px] text-faint">open</div>
                    </div>
                    <div className="text-right w-[84px] hidden md:block">
                      <div className="text-[13px] font-bold tn">{money(a.invested)}</div>
                      <div className="text-[11px] text-faint">{Math.round(Math.max(0, 1 - a.invested / NOTIONAL) * 100)}% cash</div>
                    </div>
                    <span className="text-faint text-[15px] transition-transform" style={{ transform: isOpen ? "rotate(90deg)" : "none" }}>›</span>
                  </button>

                  {isOpen && (
                    <div className="border-t" style={{ borderColor: "#f0eef6" }}>
                      <div className="grid px-5 py-2.5 text-[11px] text-faint font-bold" style={{ gridTemplateColumns: "1.1fr .8fr .8fr .7fr .8fr .8fr .8fr .7fr" }}>
                        <span>Ticker</span><span className="text-right">Entry</span><span className="text-right">Last</span>
                        <span className="text-right">Ret%</span><span className="text-right">Shares</span><span className="text-right">Value</span>
                        <span className="text-right">Stop/Tgt</span><span className="text-right">Status</span>
                      </div>
                      <div className="scroll-y" style={{ maxHeight: 380 }}>
                        {a.positions.slice().sort((x, y) => (y.return_pct ?? 0) - (x.return_pct ?? 0)).map((p) => (
                          <div key={p.id} className="grid px-5 py-2 text-[12.5px] items-center tn border-t" style={{ gridTemplateColumns: "1.1fr .8fr .8fr .7fr .8fr .8fr .8fr .7fr", borderColor: "#f6f4fb" }}>
                            <span className="font-bold">{p.ticker}</span>
                            <span className="text-right">{num(p.entry, 1)}</span>
                            <span className="text-right">{p.last_price != null ? num(p.last_price, 1) : "—"}</span>
                            <span className={`text-right font-bold ${signClass(p.return_pct)}`}>{pctSigned(p.return_pct)}</span>
                            <span className="text-right text-faint">{p.shares}</span>
                            <span className="text-right text-faint">{money((p.last_price ?? p.entry) * p.shares)}</span>
                            <span className="text-right text-faint text-[11px]">{p.stop != null ? num(p.stop, 0) : "—"}/{p.target != null ? num(p.target, 0) : "—"}</span>
                            <span className="text-right">{p.status === "open" ? <span className="text-faint">open</span> : <Pill tone={p.reason === "target" ? "good" : "bad"}>{p.reason ?? "closed"}</Pill>}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
