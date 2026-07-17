"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { PaperEquity, PaperPosition, PaperSim, ScoreRow } from "@/lib/types";
import { dateShort, money, num, pctSigned, signClass } from "@/lib/format";
import { Card, Pill, StatCard } from "@/components/ui";
import { EquityChart } from "@/components/charts";

// Notional capital per strategy — used to surface how much is actually deployed vs. sitting in cash
// (the ₹1L books are only partly invested when weights × ₹1L round below one share).
const NOTIONAL = 100000;

// Books started before this date are the original 6-Jul cohort; at/after it, the survivor cohort.
const SURVIVOR_CUTOFF = "2026-07-10";

// Friendly labels for the tracked strategies (strategy_id -> shown name + one-line what).
const LABELS: Record<string, { name: string; note: string }> = {
  DVM_user: { name: "DVM (yours)", note: "mcap>500 · avg(D,V,M)≥55 · top-10 by DVM blend" },
  DVM_dm_m_20: { name: "DVM · durability+momentum", note: "top-20 · monthly" },
  BLEND_70_30: { name: "Blend 70/30", note: "70% momentum + 30% low-vol" },
  MOM_roc252_m_20: { name: "Momentum (12-mo)", note: "top-20 · monthly" },
  CMP_valmom_m_20: { name: "Value + momentum", note: "top-20 · monthly" },
  DVM_all_w_10: { name: "DVM all-3 · weekly", note: "5y-study survivor · top-10 · weekly" },
  DVM_all_m_10: { name: "DVM all-3 · monthly", note: "5y-study survivor · top-10 · monthly" },
  MOM_roc252_m_10: { name: "Momentum (12-mo) · top-10", note: "5y-study survivor · monthly" },
};

interface Agg {
  sid: string; positions: PaperPosition[]; open: number; closed: number;
  invested: number; value: number; pnl: number; pnlPct: number; wins: number; marked: number;
  start: string; days: number;
}

function daysBetween(a: string, b: string): number {
  return Math.max(0, Math.round((+new Date(b) - +new Date(a)) / 86400000));
}

function aggregate(sid: string, ps: PaperPosition[], today: string): Agg {
  let invested = 0, value = 0, wins = 0, open = 0, closed = 0, marked = 0;
  let start = ps[0]?.entry_date ?? today;
  for (const p of ps) {
    const cost = p.entry * p.shares;
    const mark = (p.last_price ?? p.entry) * p.shares;
    invested += cost; value += mark;
    if (p.status === "open") open++; else closed++;
    if (p.last_price != null) marked++;
    if ((p.return_pct ?? 0) > 0) wins++;
    if (p.entry_date < start) start = p.entry_date;
  }
  const pnl = value - invested;
  return { sid, positions: ps, open, closed, invested, value, pnl,
    pnlPct: invested ? pnl / invested : 0, wins, marked, start, days: daysBetween(start, today) };
}

function BookCard({ a, i, netPnl, equity, sim, isOpen, onToggle }: {
  a: Agg; i: number; netPnl: number | null;
  equity?: { start: string; points: [string, number][]; benchmark: [string, number][] };
  sim?: { points: [string, number][]; ret?: number | null; error?: string };
  isOpen: boolean; onToggle: () => void;
}) {
  const lab = LABELS[a.sid] ?? { name: a.sid, note: a.sid === "dvm-monthly" ? "older test book" : "" };
  const benchRet = equity?.benchmark?.length ? equity.benchmark[equity.benchmark.length - 1][1] : null;
  const chartStrategy = useMemo(
    () => (equity?.points ?? []).map(([d, r]) => [d, (1 + r) * NOTIONAL] as [string, number]),
    [equity]);
  const chartBench = useMemo(
    () => (equity?.benchmark ?? []).map(([d, r]) => [d, (1 + r) * NOTIONAL] as [string, number]),
    [equity]);
  const simRet = sim?.points?.length ? sim.points[sim.points.length - 1][1] : null;

  return (
    <Card className="overflow-hidden">
      <button type="button" onClick={onToggle} className="w-full text-left px-5 py-4 flex items-center gap-4 wf-row" aria-expanded={isOpen}>
        <span className="text-[13px] font-extrabold text-faint w-5 tn">{i + 1}</span>
        <div className="flex-1 min-w-0">
          <div className="font-extrabold text-[15px]">{lab.name}</div>
          <div className="text-[11.5px] text-faint truncate">
            {lab.note} · since <b>{dateShort(a.start)}</b> · {a.days}d
          </div>
        </div>
        <div className="text-right w-[92px]">
          <div className={`font-extrabold text-[16px] tn ${signClass(a.pnl)}`}>{pctSigned(a.pnlPct)}</div>
          <div className="text-[11px] text-faint tn">{money(a.pnl)} gross</div>
        </div>
        <div className="text-right w-[92px] hidden sm:block">
          <div className={`text-[13px] font-bold tn ${signClass(netPnl)}`}>{netPnl != null ? money(netPnl) : "—"}</div>
          <div className="text-[11px] text-faint">net of costs</div>
        </div>
        <div className="text-right w-[80px] hidden sm:block">
          <div className={`text-[13px] font-bold tn ${signClass(benchRet)}`}>{benchRet != null ? pctSigned(benchRet) : "—"}</div>
          <div className="text-[11px] text-faint">Nifty500</div>
        </div>
        <div className="text-right w-[64px] hidden md:block">
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
          {chartStrategy.length > 1 && (
            <div className="px-5 pt-4">
              <div className="text-[11px] text-faint font-bold mb-1">
                Book vs Nifty500 (₹{NOTIONAL / 1000}k rebased · gross)
              </div>
              <EquityChart strategy={chartStrategy} benchmark={chartBench} height={180} />
            </div>
          )}
          {(sim || simRet != null) && (
            <div className="mx-5 mt-3 px-3 py-2 rounded-[10px] text-[12px]" style={{ background: "#fef7e8" }}>
              <Pill tone="warn">SIMULATED</Pill>{" "}
              entries from <b>29 Jun</b> would sit at{" "}
              <b className={`tn ${signClass(simRet)}`}>{simRet != null ? pctSigned(simRet) : "n/a"}</b>
              {sim?.error ? <span className="text-faint"> (sim unavailable: {sim.error})</span> : null}
              <span className="text-faint"> — mechanical engine run, not the live record.</span>
            </div>
          )}
          <div className="grid px-5 py-2.5 mt-2 text-[11px] text-faint font-bold" style={{ gridTemplateColumns: "1fr .8fr .7fr .7fr .65fr .7fr .75fr .7fr .7fr" }}>
            <span>Ticker</span><span className="text-right">Entered</span><span className="text-right">Entry</span>
            <span className="text-right">Last</span><span className="text-right">Ret%</span><span className="text-right">Shares</span>
            <span className="text-right">Value</span><span className="text-right">Stop/Tgt</span><span className="text-right">Status</span>
          </div>
          <div className="scroll-y" style={{ maxHeight: 380 }}>
            {a.positions.slice().sort((x, y) => (y.return_pct ?? 0) - (x.return_pct ?? 0)).map((p) => (
              <div key={p.id} className="grid px-5 py-2 text-[12.5px] items-center tn border-t" style={{ gridTemplateColumns: "1fr .8fr .7fr .7fr .65fr .7fr .75fr .7fr .7fr", borderColor: "#f6f4fb" }}>
                <span className="font-bold">{p.ticker}</span>
                <span className="text-right text-faint">{dateShort(p.entry_date)}</span>
                <span className="text-right">{num(p.entry, 1)}</span>
                <span className="text-right">{p.last_price != null ? num(p.last_price, 1) : "—"}</span>
                <span className={`text-right font-bold ${signClass(p.return_pct)}`}>{pctSigned(p.return_pct)}</span>
                <span className="text-right text-faint">{p.shares}</span>
                <span className="text-right text-faint">{money((p.last_price ?? p.entry) * p.shares)}</span>
                <span className="text-right text-faint text-[11px]">{p.stop != null ? num(p.stop, 0) : "—"}/{p.target != null ? num(p.target, 0) : "—"}</span>
                <span className="text-right">
                  {p.status === "open"
                    ? <span className="text-faint">open</span>
                    : <span title={p.exit_date ? `exited ${dateShort(p.exit_date)}` : undefined}>
                        <Pill tone={p.reason === "target" ? "good" : "bad"}>{p.reason ?? "closed"}</Pill>
                      </span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

export default function PaperPage() {
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [scoreRows, setScoreRows] = useState<ScoreRow[]>([]);
  const [equity, setEquity] = useState<PaperEquity | null>(null);
  const [sim, setSim] = useState<PaperSim | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [markMsg, setMarkMsg] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  function load() {
    api.paperPositions().then(setPositions).catch((e) => setErr(e.message));
    api.scoreboard().then(setScoreRows).catch(() => {});
    api.paperEquity().then(setEquity).catch(() => {});
    api.paperSim().then(setSim).catch(() => {}); // optional: page works without the SIM file
  }
  useEffect(load, []);

  async function markNow() {
    setBusy(true); setErr(null); setMarkMsg(null);
    try {
      const res = (await api.markPaper()) as { mark?: { open_marked?: number; newly_closed?: number } };
      const m = res?.mark ?? {};
      setMarkMsg(`✓ marked ${m.open_marked ?? "?"} open positions · ${m.newly_closed ?? 0} newly closed · ${new Date().toLocaleTimeString()}`);
      load();
    } catch (e) { setErr(`mark failed: ${(e as Error).message}`); }
    finally { setBusy(false); }
  }

  const today = new Date().toISOString().slice(0, 10);
  const aggs = useMemo(() => {
    const by: Record<string, PaperPosition[]> = {};
    for (const p of positions) (by[p.strategy_id ?? "unassigned"] ||= []).push(p);
    return Object.entries(by).map(([sid, ps]) => aggregate(sid, ps, today))
      .sort((a, b) => b.pnlPct - a.pnlPct);
  }, [positions, today]);

  const originals = aggs.filter((a) => a.start < SURVIVOR_CUTOFF);
  const survivors = aggs.filter((a) => a.start >= SURVIVOR_CUTOFF);
  const netBy = useMemo(() => Object.fromEntries(scoreRows.map((r) => [r.strategy_id, r.net_pnl ?? null])), [scoreRows]);

  const lastMark = useMemo(() => {
    const ds = positions.map((p) => p.last_date).filter(Boolean) as string[];
    return ds.sort().at(-1) ?? null;
  }, [positions]);

  const expStart = originals.length ? originals.map((a) => a.start).sort()[0] : null;
  const totalPnl = aggs.reduce((a, x) => a + x.pnl, 0);
  const totalNet = scoreRows.reduce((a, x) => a + (x.net_pnl ?? 0), 0);
  const benchSince = useMemo(() => {
    if (!equity || !originals.length) return null;
    const b = equity.books[originals[0].sid]?.benchmark;
    return b?.length ? b[b.length - 1][1] : null;
  }, [equity, originals]);

  const renderGroup = (label: string, list: Agg[], offset: number) => (
    list.length > 0 && (
      <div className="mb-5">
        <div className="text-[12px] font-extrabold text-faint uppercase tracking-wide mb-2">{label}</div>
        <div className="flex flex-col gap-2.5">
          {list.map((a, i) => (
            <BookCard
              key={a.sid} a={a} i={offset + i} netPnl={netBy[a.sid] ?? null}
              equity={equity?.books[a.sid]} sim={sim?.books[a.sid]}
              isOpen={open === a.sid} onToggle={() => setOpen(open === a.sid ? null : a.sid)}
            />
          ))}
        </div>
      </div>
    )
  );

  return (
    <div>
      <div className="flex items-end justify-between mt-6 mb-4 animate-rise">
        <div>
          <h1 className="text-[34px] font-extrabold tracking-tight">Paper trades</h1>
          <p className="text-muted text-[14px] mt-1.5 max-w-[640px]">
            A zero-risk live dry-run on real NSE end-of-day prices — no money at stake. Two cohorts:
            the original five (since 6 Jul) and the 5y-study survivors (since 17 Jul). Watch them
            compete before funding one.
          </p>
        </div>
        <div className="text-right">
          <button className="btn btn-ink" disabled={busy} onClick={markNow}>{busy ? "marking…" : "↻ Mark to market"}</button>
          {markMsg && <div className="text-[11.5px] text-gain mt-1.5 tn">{markMsg}</div>}
        </div>
      </div>

      {err && <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}><span className="text-loss text-[13px]">{err}</span></Card>}

      {/* the basics, up front */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2.5 mb-4">
        <StatCard label="Experiment start" value={expStart ? dateShort(expStart) : "—"} sub={expStart ? `${daysBetween(expStart, today)} days live` : ""} />
        <StatCard label="Books" value={String(aggs.length)} sub={`${positions.length} positions`} />
        <StatCard label="Gross P&L" value={money(totalPnl)} sub="before costs" tone={totalPnl >= 0 ? "lime" : "white"} />
        <StatCard label="Net P&L" value={money(totalNet)} sub="after brokerage/STT/slippage" tone={totalNet >= 0 ? "lime" : "white"} />
        <StatCard label="Nifty500 same period" value={benchSince != null ? pctSigned(benchSince) : "—"} sub="benchmark return" />
      </div>

      {/* honesty / freshness banner */}
      <Card className="px-4 py-3 mb-4 text-[12px] text-muted" style={{ background: "#f7f5fc" }}>
        <b className="text-ink">How this works:</b> prices are NSE Bhavcopy <b>end-of-day</b> (not intraday),
        refreshed weekday nights; P&amp;L marks to the last trading day{lastMark ? <> — currently <b className="text-ink">{lastMark}</b></> : ""}.
        Headline card P&amp;L is <b>gross of costs</b>; the net column deducts modelled brokerage/STT/slippage.
        Each position enters at the close it was opened on, so day-0 P&amp;L starts at zero. Books are only
        partly invested when a name&apos;s weight rounds below one share — see <b>cash %</b> per strategy.
        The yellow SIM blocks are <b>simulated</b> engine runs from 29 Jun, kept strictly apart from the
        live record. You still place every real order yourself.
      </Card>

      {positions.length === 0 ? (
        <Card className="px-5 py-10 text-center text-[13px] text-muted">No paper positions yet.</Card>
      ) : (
        <>
          {renderGroup("Originals — live since 6 Jul", originals, 0)}
          {renderGroup("Survivors — live since 17 Jul (5y-study winners)", survivors, originals.length)}
        </>
      )}
    </div>
  );
}
