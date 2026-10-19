"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { PaperEquity, PaperEquityBook, PaperPosition, ScoreRow } from "@/lib/types";
import { dateShort, money, num, pct, pctSigned, signClass } from "@/lib/format";
import { Card, Pill, StatCard } from "@/components/ui";
import { EquityChart } from "@/components/charts";

// Fallback notional only. The API reports each book's own notional (equity.books[sid].notional),
// which is what the page uses. Every book is replayed from 29 Jun 2026 on a single ₹5L notional
// (iter-197), so the fallback — reached only when a book has no equity row — matches it.
const NOTIONAL_FALLBACK = 500000;

// One naming pattern for every book: "<strategy> · top N · <frequency>".
const LABELS: Record<string, string> = {
  DVM_user: "DVM (your screen) · top 10 · monthly",
  DVM_dm_m_20: "Durability + Momentum · top 20 · monthly",
  MOM_roc252_m_20: "12-month Momentum · top 20 · monthly",
  MOM_roc252_m_10: "12-month Momentum · top 10 · monthly",
  CMP_valmom_m_20: "Value + Momentum · top 20 · monthly",
  DVM_all_w_10: "DVM (all three) · top 10 · weekly",
  DVM_all_m_10: "DVM (all three) · top 10 · monthly",
  BLEND_70_30: "Momentum 70 / Low-vol 30 · top 20 each · monthly",
};

// Every book also sits behind the engine's point-in-time ₹500cr membership floor, so the universe
// text starts there for all eight; only the extra screens differ.
const rule = (n: number | string, by: string, freq: string, extra: string) =>
  `Top ${n} by ${by}, equal weight, rebalanced ${freq} · universe: mcap ≥ ₹500cr, ${extra}`;
const DVM3 = "Durability + Valuation + Momentum";
const RULES: Record<string, string> = {
  DVM_user: rule(10, DVM3, "monthly", "ADTV ≥ ₹5cr, avg DVM ≥ 55"),
  DVM_dm_m_20: rule(20, "Durability + Momentum", "monthly", "ADTV ≥ ₹0.5cr"),
  MOM_roc252_m_20: rule(20, "12-month price change", "monthly", "ADTV ≥ ₹0.5cr"),
  MOM_roc252_m_10: rule(10, "12-month price change", "monthly", "ADTV ≥ ₹0.5cr"),
  CMP_valmom_m_20: rule(20, "low PE + 6-month price change", "monthly", "ADTV ≥ ₹0.5cr"),
  DVM_all_w_10: rule(10, DVM3, "weekly", "ADTV ≥ ₹0.5cr"),
  DVM_all_m_10: rule(10, DVM3, "monthly", "ADTV ≥ ₹0.5cr"),
  BLEND_70_30: rule("20 + 20", "12-month price change (70%) / low volatility (30%)", "monthly", "ADTV ≥ ₹0.5cr"),
};

const REASON_LABEL: Record<string, string> = { rebalance: "rebalance", stop: "stop-loss", target: "target hit", resize: "resize" };
const reasonLabel = (r: string | null) => (r ? REASON_LABEL[r] ?? r : "closed");
const reasonTone = (r: string | null): "good" | "bad" | "neutral" => (r === "target" ? "good" : r === "stop" ? "bad" : "neutral");

const HOLD_COLS = "1fr .8fr .7fr .7fr .7fr .6fr .8fr .6fr .8fr";
const HIST_COLS = "1fr .7fr .7fr .7fr .7fr .7fr .8fr .5fr .8fr";

interface Agg {
  sid: string; positions: PaperPosition[]; open: number; closed: number; pending: number;
  invested: number; openCost: number; pendingCapital: number; committed: number;
  value: number; pnl: number;
  wins: number; marked: number; start: string; days: number;
}

function daysBetween(a: string, b: string): number {
  return Math.max(0, Math.round((+new Date(b) - +new Date(a)) / 86400000));
}

function aggregate(sid: string, ps: PaperPosition[], today: string): Agg {
  let invested = 0, openCost = 0, pendingCapital = 0, value = 0;
  let wins = 0, open = 0, closed = 0, pending = 0, marked = 0;
  let start = ps.find((p) => p.entry_date)?.entry_date ?? today;
  for (const p of ps) {
    // A pending row has no entry, shares or price yet — it is capital COMMITTED to a fill at the
    // next session's open, not capital deployed. It contributes nothing to invested/value/P&L, and
    // it is emphatically not "closed" (#863: it used to fall into the else branch below, so after
    // the Rs5L resize all eight books reported every holding closed and nothing open).
    if (p.status === "pending") {
      pending++;
      pendingCapital += p.planned_capital ?? 0;
      continue;
    }
    if (p.entry == null || p.shares == null) continue;   // void, or an incomplete row
    const cost = p.entry * p.shares;
    // A stop/target exit books the stop/target level as `exit` while last_price stays that day's
    // close; the equity curve uses `exit`, so the ₹ line must too or it drifts off the % above it.
    const mark = ((p.status === "closed" && p.exit != null ? p.exit : p.last_price) ?? p.entry) * p.shares;
    invested += cost; value += mark;
    // `invested` is every rupee ever deployed, so on a book that has recycled capital it exceeds
    // the notional and reads as nonsense next to a cash figure (₹1,54,885 on a ₹1L book).
    // openCost is what is actually at work right now (iter-171).
    if (p.status === "open") { openCost += cost; open++; } else closed++;
    if (p.last_price != null) marked++;
    if ((p.return_pct ?? 0) > 0) wins++;
    if (p.entry_date && p.entry_date < start) start = p.entry_date;
  }
  const pnl = value - invested;
  return { sid, positions: ps, open, closed, pending, invested, openCost, pendingCapital,
    committed: openCost + pendingCapital, value, pnl, wins, marked, start, days: daysBetween(start, today) };
}

// Current value of a holding: planned capital while queued, else marked at the last price.
function holdingValue(p: PaperPosition): number | null {
  if (p.status === "pending") return p.planned_capital ?? 0;
  return p.entry != null && p.shares != null ? (p.last_price ?? p.entry) * p.shares : null;
}

function BookCard({ a, i, score, equity, isOpen, onToggle }: {
  a: Agg; i: number; score?: ScoreRow;
  equity?: PaperEquityBook;
  isOpen: boolean; onToggle: () => void;
}) {
  const [tab, setTab] = useState<"holdings" | "history">("holdings");
  const title = LABELS[a.sid] ?? a.sid;
  const rules = RULES[a.sid];
  const benchRet = equity?.benchmark?.length ? equity.benchmark[equity.benchmark.length - 1][1] : null;
  // Headline return comes from the API's NAV curve only. After the replay the curve and the rupee
  // P&L share one basis (₹5L since the start); with no curve the % shows "—" rather than falling
  // back to pnl/invested, a different and diluted measure (iter-197).
  const st = equity?.stats;
  const grossRet = st?.gross_return ?? null;
  const netRet = st?.net_return ?? null;
  // min_cash_pct is the LOWEST the cash balance ever got: capital that was never deployed even at
  // the book's most-invested moment, i.e. the permanent drag (iter-171, item 1236).
  const cashPct = st ? st.min_cash_pct : null;
  const unpriced = st?.unpriced_holdings ?? [];
  const notional = equity?.notional ?? NOTIONAL_FALLBACK;
  const chartStrategy = useMemo(
    () => (equity?.points ?? []).map(([d, r]) => [d, (1 + r) * notional] as [string, number]),
    [equity, notional]);
  const chartBench = useMemo(
    () => (equity?.benchmark ?? []).map(([d, r]) => [d, (1 + r) * notional] as [string, number]),
    [equity, notional]);

  const holdings = useMemo(() => {
    const rows = a.positions.filter((p) => p.status === "open" || p.status === "pending")
      .map((p) => ({ p, v: holdingValue(p) }))
      .sort((x, y) => (y.v ?? 0) - (x.v ?? 0));
    return { rows, total: rows.reduce((s, r) => s + (r.v ?? 0), 0) };
  }, [a.positions]);

  // Closed trades grouped by exit date, newest first.
  const history = useMemo(() => {
    const closed = a.positions.filter((p) => p.status === "closed");
    const by: Record<string, PaperPosition[]> = {};
    for (const p of closed) (by[p.exit_date ?? ""] ||= []).push(p);
    const groups = Object.entries(by)
      .sort(([x], [y]) => (x === y ? 0 : x === "" ? 1 : y === "" ? -1 : x < y ? 1 : -1))
      .map(([date, ps]) => ({
        date,
        reasons: [...new Set(ps.map((p) => reasonLabel(p.reason)))].join(" / "),
        rows: ps.slice().sort((x, y) => (y.return_pct ?? 0) - (x.return_pct ?? 0)),
      }));
    return { count: closed.length, groups };
  }, [a.positions]);

  return (
    <Card className="overflow-hidden">
      <button type="button" onClick={onToggle} className="w-full text-left px-5 py-4 flex items-center gap-4 wf-row" aria-expanded={isOpen}>
        <span className="text-[13px] font-extrabold text-faint w-5 tn">{i + 1}</span>
        <div className="flex-1 min-w-0">
          <div className="font-extrabold text-[15px]">{title}</div>
          <div className="text-[11.5px] text-faint truncate">
            since <b>{dateShort(a.start)}</b> · {a.days} days
          </div>
        </div>
        <div className="text-right w-[92px]">
          <div className={`font-extrabold text-[16px] tn ${signClass(grossRet)}`}>{pctSigned(grossRet)}</div>
          <div className="text-[11px] text-faint tn">{money(a.pnl)} gross</div>
        </div>
        <div className="text-right w-[92px] hidden sm:block">
          <div className={`text-[13px] font-bold tn ${signClass(netRet)}`}>{pctSigned(netRet)}</div>
          <div className="text-[11px] text-faint">net of costs</div>
        </div>
        <div className="text-right w-[80px] hidden sm:block">
          <div className={`text-[13px] font-bold tn ${signClass(benchRet)}`}>{pctSigned(benchRet)}</div>
          <div className="text-[11px] text-faint">Nifty500</div>
        </div>
        <div className="text-right w-[64px] hidden md:block">
          <div className="text-[13px] font-bold tn">{a.pending > 0 ? a.pending : a.open}</div>
          <div className="text-[11px] text-faint">{a.pending > 0 ? "queued" : "open"}</div>
        </div>
        <div className="text-right w-[84px] hidden md:block">
          <div className="text-[13px] font-bold tn">{money(a.committed)}</div>
          <div className="text-[11px] text-faint">
            {/* While entries are queued the book is neither invested nor idle — the capital is
                committed and fills at the next open. min_cash_pct is a HISTORICAL floor, so
                showing it here would describe a book that no longer exists (#863). */}
            {a.pending > 0
              ? "committed · fills next open"
              : cashPct == null
                ? `${Math.round(Math.max(0, 1 - a.openCost / notional) * 100)}% cash`
                : cashPct < 0
                  // A negative floor is not idle cash — the book briefly spent money it did not
                  // have. Labelling it "-1% idle cash" hides an overdraw (iter-171, item 1235).
                  ? `overdrew ${money(Math.abs(st?.min_cash ?? 0))}`
                  : `${Math.round(cashPct * 100)}% idle cash`}
          </div>
        </div>
        <span className="text-faint text-[15px] transition-transform" style={{ transform: isOpen ? "rotate(90deg)" : "none" }}>›</span>
      </button>

      {isOpen && (
        <div className="border-t" style={{ borderColor: "#f0eef6" }}>
          {rules && <div className="px-5 pt-4 text-[11.5px] text-faint">{rules}</div>}
          {unpriced.length > 0 && (
            <div className="mx-5 mt-4 px-3 py-2 rounded-[10px] text-[12px]" style={{ background: "#fdeeee" }}>
              <Pill tone="warn">UNPRICED</Pill>{" "}
              no live price for <b>{unpriced.join(", ")}</b> on some days — held at entry cost there,
              so this book&apos;s path understates movement it actually had.
            </div>
          )}
          {score && (
            <div className="px-5 pt-4 flex flex-wrap gap-x-6 gap-y-1 text-[12px]">
              <span className="text-faint">
                Win rate{" "}
                <b className="tn">{score.book_win_rate != null ? pctSigned(score.book_win_rate).replace("+", "") : "—"}</b>{" "}
                whole book
              </span>
              <span className="text-faint">
                <b className="tn">{score.closed_win_rate != null ? pctSigned(score.closed_win_rate).replace("+", "") : "—"}</b>{" "}
                on closed trades only
              </span>
              <span className="text-faint">
                {score.closed} closed · {score.open} open
              </span>
              {st && (
                <span className="text-faint">
                  Max drawdown <b className="tn">{pctSigned(st.max_drawdown)}</b>
                </span>
              )}
              {st?.cash_went_negative && (
                <span className="text-faint">
                  <Pill tone="warn">OVERDREW</Pill> cash floor {money(st.min_cash)}
                </span>
              )}
            </div>
          )}
          {chartStrategy.length > 1 && (
            <div className="px-5 pt-4">
              <div className="text-[11px] text-faint font-bold mb-1">
                Book vs Nifty500 (₹{Math.round(notional / 1000)}k rebased · gross)
              </div>
              <EquityChart strategy={chartStrategy} benchmark={chartBench} height={180} />
            </div>
          )}
          <div className="px-5 pt-4 flex">
            <div className="flex gap-0.5 p-0.5 rounded-lg" style={{ background: "#f1eef8" }}>
              {(["holdings", "history"] as const).map((t) => (
                <button key={t} type="button" className="wf-seg" data-active={tab === t ? "1" : "0"} style={{ padding: "6px 12px", fontSize: 12 }}
                  onClick={() => setTab(t)}>
                  {t === "holdings" ? `Holdings (${holdings.rows.length})` : `History (${history.count} closed)`}
                </button>
              ))}
            </div>
          </div>
          {tab === "holdings" ? (
            <>
              <div className="grid px-5 py-2.5 mt-2 text-[11px] text-faint font-bold" style={{ gridTemplateColumns: HOLD_COLS }}>
                <span>Ticker</span><span className="text-right">Since</span><span className="text-right">Entry</span>
                <span className="text-right">Last</span><span className="text-right">Return</span><span className="text-right">Shares</span>
                <span className="text-right">Value</span><span className="text-right">Weight</span><span className="text-right">Stop/Target</span>
              </div>
              <div className="scroll-y" style={{ maxHeight: 380 }}>
                {holdings.rows.length === 0 && <div className="px-5 py-6 text-[13px] text-faint border-t" style={{ borderColor: "#f6f4fb" }}>No holdings.</div>}
                {holdings.rows.map(({ p, v }) => (
                  <div key={p.id} className="grid px-5 py-2 text-[12.5px] items-center tn border-t" style={{ gridTemplateColumns: HOLD_COLS, borderColor: "#f6f4fb" }}>
                    <span className="font-bold">{p.ticker}</span>
                    <span className="text-right text-faint">
                      {p.status === "pending"
                        // Queued by a rebalance, fills at the next session's open. Showing this as a
                        // red "closed" pill was #863 — it made a live book look liquidated.
                        ? <span title="queued by the last rebalance — fills at the next session's open">
                            <Pill tone="warn">queued</Pill>
                          </span>
                        : dateShort(p.entry_date)}
                    </span>
                    <span className="text-right">{p.entry != null ? num(p.entry, 1) : "—"}</span>
                    <span className="text-right">{p.last_price != null ? num(p.last_price, 1) : "—"}</span>
                    <span className={`text-right font-bold ${signClass(p.return_pct)}`}>{pctSigned(p.return_pct)}</span>
                    <span className="text-right text-faint">{p.shares ?? "—"}</span>
                    <span className="text-right text-faint">{money(v)}</span>
                    <span className="text-right text-faint">{v != null && holdings.total > 0 ? pct(v / holdings.total, 1) : "—"}</span>
                    <span className="text-right text-faint text-[11px]">{p.stop != null ? num(p.stop, 0) : "—"}/{p.target != null ? num(p.target, 0) : "—"}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="grid px-5 py-2.5 mt-2 text-[11px] text-faint font-bold" style={{ gridTemplateColumns: HIST_COLS }}>
                <span>Ticker</span><span className="text-right">Bought</span><span className="text-right">Sold</span>
                <span className="text-right">Entry</span><span className="text-right">Exit</span><span className="text-right">Return</span>
                <span className="text-right">P&amp;L</span><span className="text-right">Held</span><span className="text-right">Why</span>
              </div>
              <div className="scroll-y" style={{ maxHeight: 380 }}>
                {history.count === 0 && <div className="px-5 py-6 text-[13px] text-faint border-t" style={{ borderColor: "#f6f4fb" }}>No closed trades yet.</div>}
                {history.groups.map((g) => (
                  <div key={g.date || "undated"}>
                    <div className="px-5 py-1.5 text-[11.5px] font-extrabold text-muted tn border-t" style={{ background: "#f7f5fc", borderColor: "#f0eef6" }}>
                      {dateShort(g.date)} · {g.reasons} · {g.rows.length} sold
                    </div>
                    {g.rows.map((p) => {
                      const pnl = p.exit != null && p.entry != null && p.shares != null ? (p.exit - p.entry) * p.shares : null;
                      return (
                        <div key={p.id} className="grid px-5 py-2 text-[12.5px] items-center tn border-t" style={{ gridTemplateColumns: HIST_COLS, borderColor: "#f6f4fb" }}>
                          <span className="font-bold">{p.ticker}</span>
                          <span className="text-right text-faint">{dateShort(p.entry_date)}</span>
                          <span className="text-right text-faint">{dateShort(p.exit_date)}</span>
                          <span className="text-right">{p.entry != null ? num(p.entry, 1) : "—"}</span>
                          <span className="text-right">{p.exit != null ? num(p.exit, 1) : "—"}</span>
                          <span className={`text-right font-bold ${signClass(p.return_pct)}`}>{pctSigned(p.return_pct)}</span>
                          <span className={`text-right ${signClass(pnl)}`}>{money(pnl)}</span>
                          <span className="text-right text-faint">{p.entry_date && p.exit_date ? `${daysBetween(p.entry_date, p.exit_date)}d` : "—"}</span>
                          <span className="text-right"><Pill tone={reasonTone(p.reason)}>{reasonLabel(p.reason)}</Pill></span>
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

export default function PaperPage() {
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [scoreRows, setScoreRows] = useState<ScoreRow[]>([]);
  const [equity, setEquity] = useState<PaperEquity | null>(null);
  const [eqErr, setEqErr] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [markMsg, setMarkMsg] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  function loadEquity() {
    setEqErr(null);
    api.paperEquity().then(setEquity).catch((e) => setEqErr(e.message));
  }
  function load() {
    // void rows are never shown anywhere
    api.paperPositions().then((ps) => setPositions(ps.filter((p) => p.status !== "void"))).catch((e) => setErr(e.message));
    api.scoreboard().then(setScoreRows).catch(() => {});
    loadEquity();
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
  // Sorted by the headline % that is displayed (NAV gross return); books without a curve go last.
  const aggs = useMemo(() => {
    const by: Record<string, PaperPosition[]> = {};
    for (const p of positions) (by[p.strategy_id ?? "unassigned"] ||= []).push(p);
    const ret = (sid: string) => equity?.books[sid]?.stats?.gross_return ?? null;
    return Object.entries(by).map(([sid, ps]) => aggregate(sid, ps, today))
      .sort((a, b) => {
        const ra = ret(a.sid), rb = ret(b.sid);
        if (ra == null || rb == null) return ra == null ? (rb == null ? 0 : 1) : -1;
        return rb - ra;
      });
  }, [positions, equity, today]);

  const scoreBy = useMemo(() => Object.fromEntries(scoreRows.map((r) => [r.strategy_id, r])), [scoreRows]);

  // The earliest-starting book sets the experiment start and the benchmark period.
  const first = useMemo(() => (aggs.length ? aggs.reduce((m, a) => (a.start < m.start ? a : m)) : null), [aggs]);
  const expStart = first?.start ?? null;
  const totalPnl = aggs.reduce((a, x) => a + x.pnl, 0);
  const totalNet = scoreRows.reduce((a, x) => a + (x.net_pnl ?? 0), 0);
  const benchSince = useMemo(() => {
    const b = first ? equity?.books[first.sid]?.benchmark : null;
    return b?.length ? b[b.length - 1][1] : null;
  }, [equity, first]);

  return (
    <div>
      <div className="flex items-end justify-between mt-6 mb-4 animate-rise">
        <div>
          <h1 className="text-[34px] font-extrabold tracking-tight">Paper trades</h1>
        </div>
        <div className="text-right">
          <button className="btn btn-ink" disabled={busy} onClick={markNow}>{busy ? "marking…" : "↻ Mark to market"}</button>
          {markMsg && <div className="text-[11.5px] text-gain mt-1.5 tn">{markMsg}</div>}
        </div>
      </div>

      {err && <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}><span className="text-loss text-[13px]">{err}</span></Card>}
      {eqErr && (
        <Card className="px-4 py-3 mb-4 flex items-center justify-between gap-3" style={{ background: "#fdeaf1" }}>
          <span className="text-loss text-[13px]">Return curves could not be loaded — returns show “—” until they do. ({eqErr})</span>
          <button type="button" className="btn btn-soft shrink-0" style={{ padding: "7px 14px", fontSize: 12 }} onClick={loadEquity}>Retry</button>
        </Card>
      )}

      {/* the basics, up front */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2.5 mb-4">
        <StatCard label="Experiment start" value={expStart ? dateShort(expStart) : "—"} sub={expStart ? `${daysBetween(expStart, today)} days live` : ""} />
        <StatCard label="Books" value={String(aggs.length)} sub={`${positions.length} positions`} />
        <StatCard label="Gross P&L" value={money(totalPnl)} sub="before costs" tone={totalPnl >= 0 ? "lime" : "white"} />
        <StatCard label="Net P&L" value={money(totalNet)} sub="after modelled NSE costs" tone={totalNet >= 0 ? "lime" : "white"} />
        <StatCard label="Nifty500 same period" value={benchSince != null ? pctSigned(benchSince) : "—"} sub="benchmark return" />
      </div>

      {positions.length === 0 ? (
        <Card className="px-5 py-10 text-center text-[13px] text-muted">No paper positions yet.</Card>
      ) : (
        <div className="flex flex-col gap-2.5 mb-5">
          {aggs.map((a, i) => (
            <BookCard
              key={a.sid} a={a} i={i} score={scoreBy[a.sid]} equity={equity?.books[a.sid]}
              isOpen={open === a.sid} onToggle={() => setOpen(open === a.sid ? null : a.sid)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
