"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { FamilyRow, LeaderboardRow, LeaderboardsData, VerdictRow } from "@/lib/types";
import { num, pct, pctSigned, signClass } from "@/lib/format";
import { Card, Pill, Segmented } from "@/components/ui";

type BoardKey = "overall" | "postcovid" | "precovid" | "families" | "verdicts";
type SortKey = "cagr" | "sharpe" | "maxdd";

const BOARD_OPTIONS: { value: BoardKey; label: string }[] = [
  { value: "overall", label: "Overall 10y" },
  { value: "postcovid", label: "Post-COVID 5y" },
  { value: "precovid", label: "Pre-COVID" },
  { value: "families", label: "Families" },
  { value: "verdicts", label: "Verdicts" },
];

const VERDICT_TONE: Record<VerdictRow["verdict"], "good" | "bad" | "warn" | "neutral"> = {
  survivor: "good",
  "regime-bet": "warn",
  noise: "bad",
  incumbent: "neutral",
  "incumbent-flag": "warn",
  finalist: "neutral",
};

function BenchStrip({ b, window: w }: { b?: { cagr: number | null; sharpe: number | null; maxdd: number | null } | null; window: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-muted mb-3">
      <span className="tn">{w}</span>
      {b && (
        <span>
          Nifty500: <b className="tn">{pct(b.cagr, 1)}</b> CAGR · <b className="tn">{num(b.sharpe)}</b> Sharpe ·{" "}
          <b className="tn">{pct(b.maxdd, 1)}</b> MaxDD
        </span>
      )}
    </div>
  );
}

function MetricsHeader({ sort, setSort, extra }: { sort: SortKey; setSort: (s: SortKey) => void; extra?: string }) {
  const th = (key: SortKey, label: string) => (
    <button
      type="button"
      onClick={() => setSort(key)}
      className={`text-right font-bold transition-colors ${sort === key ? "text-ink" : "text-faint hover:text-ink"}`}
    >
      {label}
      {sort === key ? " ↓" : ""}
    </button>
  );
  return (
    <div
      className="grid px-5 py-2.5 text-[11px] text-faint font-bold border-b"
      style={{ gridTemplateColumns: `28px 1.5fr .7fr ${extra ? ".9fr " : ""}.7fr .7fr .7fr`, borderColor: "#f0eef6" }}
    >
      <span>#</span>
      <span>Strategy</span>
      <span>Family</span>
      {extra && <span className="text-right">{extra}</span>}
      {th("cagr", "CAGR")}
      {th("sharpe", "Sharpe")}
      {th("maxdd", "MaxDD")}
    </div>
  );
}

function StrategyBoard({ rows, extra }: { rows: LeaderboardRow[]; extra?: "src" }) {
  const [sort, setSort] = useState<SortKey>("cagr");
  const sorted = useMemo(() => {
    const s = [...rows];
    if (sort === "maxdd") s.sort((a, b) => (b.maxdd ?? -9) - (a.maxdd ?? -9));
    else s.sort((a, b) => ((b[sort] ?? -9) as number) - ((a[sort] ?? -9) as number));
    return s;
  }, [rows, sort]);
  return (
    <Card className="overflow-hidden">
      <MetricsHeader sort={sort} setSort={setSort} extra={extra ? "Run" : undefined} />
      <div className="scroll-y" style={{ maxHeight: 560 }}>
        {sorted.map((r, i) => (
          <div
            key={r.sid}
            className="grid px-5 py-2.5 text-[12.5px] items-center tn border-t wf-row"
            style={{ gridTemplateColumns: `28px 1.5fr .7fr ${extra ? ".9fr " : ""}.7fr .7fr .7fr`, borderColor: "#f6f4fb" }}
          >
            <span className="text-faint font-bold">{i + 1}</span>
            <Link href={`/strategies/${r.sid}`} className="font-bold hover:underline truncate pr-2">
              {r.sid}
            </Link>
            <span className="text-faint">{r.family}</span>
            {extra && (
              <span className="text-right">
                {r.src === "slice" ? <Pill tone="warn">slice</Pill> : <Pill tone="neutral">fresh</Pill>}
              </span>
            )}
            <span className={`text-right font-bold ${signClass(r.cagr)}`}>{pctSigned(r.cagr)}</span>
            <span className="text-right">{num(r.sharpe)}</span>
            <span className="text-right text-loss">{pct(r.maxdd, 1)}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function FamiliesBoard({ rows }: { rows: FamilyRow[] }) {
  return (
    <Card className="overflow-hidden">
      <div
        className="grid px-5 py-2.5 text-[11px] text-faint font-bold border-b"
        style={{ gridTemplateColumns: "72px 1.6fr .7fr .7fr .5fr", borderColor: "#f0eef6" }}
      >
        <span>Family</span>
        <span>What it bets on</span>
        <span className="text-right">Median CAGR</span>
        <span className="text-right">Best</span>
        <span className="text-right">Configs</span>
      </div>
      {rows.map((f) => (
        <div
          key={f.family}
          className="grid px-5 py-3 text-[12.5px] items-center tn border-t wf-row"
          style={{ gridTemplateColumns: "72px 1.6fr .7fr .7fr .5fr", borderColor: "#f6f4fb" }}
        >
          <span className="font-extrabold">{f.family}</span>
          <span className="text-muted text-[12px]">{f.desc}</span>
          <span className={`text-right font-bold ${signClass(f.median_cagr)}`}>{pctSigned(f.median_cagr)}</span>
          <span className="text-right">{pctSigned(f.best_cagr)}</span>
          <span className="text-right text-faint">{f.n}</span>
        </div>
      ))}
    </Card>
  );
}

function VerdictsBoard({ rows }: { rows: VerdictRow[] }) {
  return (
    <div className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <Card key={r.sid} className="px-5 py-4">
          <div className="flex flex-wrap items-center gap-3 mb-2">
            <Link href={`/strategies/${r.sid}`} className="font-extrabold text-[15px] hover:underline">
              {r.sid}
            </Link>
            <Pill tone={VERDICT_TONE[r.verdict]}>{r.verdict}</Pill>
            <span className="text-[12px] text-muted flex-1 min-w-[200px]">{r.note}</span>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-[12px] tn">
            <span>
              5y <b className={signClass(r.cagr_5y)}>{pctSigned(r.cagr_5y)}</b> · {num(r.sharpe_5y)} Sharpe ·{" "}
              <span className="text-loss">{pct(r.maxdd_5y, 1)}</span> DD
            </span>
            <span>
              21-23 <b className={signClass(r.h1_cagr)}>{pctSigned(r.h1_cagr)}</b> → 24-26{" "}
              <b className={signClass(r.h2_cagr)}>{pctSigned(r.h2_cagr)}</b>
            </span>
            <span>
              pre-COVID <b className={signClass(r.pre_cagr)}>{pctSigned(r.pre_cagr)}</b>
              {r.pre_sharpe != null ? ` (${num(r.pre_sharpe)} Sharpe)` : ""}
            </span>
            <span className="text-faint">
              beat benchmark {r.seg_beat}/{r.seg_total} half-years
            </span>
          </div>
        </Card>
      ))}
    </div>
  );
}

export default function LeaderboardsPage() {
  const [data, setData] = useState<LeaderboardsData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [board, setBoard] = useState<BoardKey>("postcovid");

  useEffect(() => {
    api.leaderboards().then(setData).catch((e) => setErr(e.message));
  }, []);

  const active = data?.boards[board];

  return (
    <div>
      <div className="mt-6 mb-4 animate-rise">
        <h1 className="text-[34px] font-extrabold tracking-tight">Leaderboards</h1>
        <p className="text-muted text-[14px] mt-1.5 max-w-[680px]">
          Every board is net of costs on the survivorship-free data layer. A leaderboard is a
          starting point, not a verdict — the <b>Verdicts</b> tab shows which winners survived the
          robustness protocol and which were luck.
        </p>
      </div>

      {err && (
        <Card className="px-4 py-3 mb-4" style={{ background: "#fdeaf1" }}>
          <span className="text-loss text-[13px]">{err}</span>
        </Card>
      )}

      {!data && !err && (
        <Card className="px-5 py-10 text-center text-[13px] text-muted">Loading boards…</Card>
      )}

      {data && (
        <>
          <div className="mb-4">
            <Segmented value={board} options={BOARD_OPTIONS} onChange={setBoard} />
          </div>

          {active && (
            <div className="animate-rise" key={board}>
              <BenchStrip b={active.benchmark} window={active.window} />
              <Card className="px-4 py-2.5 mb-3 text-[12px] text-muted" style={{ background: "#f7f5fc" }}>
                {active.caption}
              </Card>
              {board === "families" ? (
                <FamiliesBoard rows={active.rows as FamilyRow[]} />
              ) : board === "verdicts" ? (
                <VerdictsBoard rows={active.rows as VerdictRow[]} />
              ) : (
                <StrategyBoard rows={active.rows as LeaderboardRow[]} extra={board === "postcovid" ? "src" : undefined} />
              )}
              <div className="text-[11px] text-faint mt-3 tn">
                dataset generated {new Date(data.generated_at).toLocaleString()} ·
                scripts/curate_leaderboards.py
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
