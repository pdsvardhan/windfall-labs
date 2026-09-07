/* ============================================================================
   Trendlyne FORECASTER Harvester  —  Windfall Labs   (to-do #857, for #26)
   ----------------------------------------------------------------------------
   Analyst consensus estimates: forward EPS, and the analyst target price.
   This is the input the valuation factor has been missing.

   WHY THIS EXISTS
   to-do #26 identified 1Y forward PE as the column behind the valuation-score
   correlation ceiling of 0.44. It cannot be exported: measured 2026-09-07, every
   "Forecaster Estimates 1Y forward PE" cell in the Data Downloader reads the
   literal string "Export NA" — 2,235 of 2,235, across both parameter sets and
   all five market-cap bands. Trendlyne blocks Forecaster fields from export and
   says so on the page.

   HOW THE DATA IS ACTUALLY REACHED (discovered 2026-09-08)
   The Forecaster page is SERVER-RENDERED — there is no XHR to intercept. Watch
   the network tab on a consensus page and the only calls are static assets plus
   getLivePrice. The whole estimate set ships inside the document, HTML-escaped,
   in one attribute:

       <div id="consensus-details" data-consensusjson="{ ...JSON... }">

   So a plain credentialed fetch is enough — no DOM rendering, no headless
   browser, no API token. The URL takes a wildcard slug, so pk alone addresses it:

       https://trendlyne.com/equity/consensus-estimates/<pk>/x/x/

   JSON shape (verified on RELIANCE pk 1127, TCS 1372, BODALCHEM 211):
       RANGE_ESTIMATES.<METRIC>.ANNUAL[] and .QUARTER[], each row carrying
       ACTUAL, AVG, HIGH, LOW, MEDIAN, NUMBER_OF_ANALYSTS, periodtype ("FY27"),
       qtr_end_date ("2027-03-31"), is_past, is_current.
       METRIC ∈ TARGET_PRICE, REVENUE, EPS, NET_INCOME, EBIT, DIVIDEND_PER_SHARE,
                FREE_CASH_FLOW, CASH_EPS, CAPEX, CASH_FLOW_SHARE,
                INTEREST_EXPENSE, DEPRECATION_AND_AMORTIZATION.
   We take EPS and TARGET_PRICE. The rest are available if a strategy ever wants
   them — add to METRICS below; the parser is generic.

   COVERAGE IS THE HEADLINE, AND IT IS NOT GOOD (full harvest 2026-09-08, 2,005
   stocks probed, banded strictly against the Rs500cr universe):
       > Rs50,000cr     186/206   90.3%
       Rs10-50,000cr    296/390   75.9%
       Rs2-10,000cr     281/632   44.5%
       Rs500-2,000cr     50/781    6.4%
       overall          813/2,005 40.5%
   Coverage does not decline gently, it collapses. Below Rs2,000cr it is
   effectively absent, and that band is 39% of the universe. Of the 77 names the
   eight live books held that day, 27 are covered (36.5% of those resolving to a
   pk); MOM_roc252_m_10 is 0 of 8, BLEND_70_30 the outlier at 52.6%. Read #26
   and adr-047 with that in mind before assuming this lifts the 0.44 ceiling.

   RUN THE MEGACAP COMPANION. This harvester takes its stock list from the base
   screener, and the base screener drops the top ~100 index names - the same
   defect trendlyne_harvester_megacap.js exists to fix. The first 2026-09-08 run
   omitted RELIANCE, HDFCBANK, LT, TITAN, ICICIBANK and ~90 more, and because
   they were never REQUESTED there was no error to see: 0 errors, 0 429s, and a
   coverage headline reading ~19% where the truth was ~36%. Feed the megacap
   symbol list through this same endpoint and re-ingest with --allow-small.

   An uncovered stock is NOT an error: it returns HTTP 200 with an empty
   RANGE_ESTIMATES and a ~75KB page (vs ~600KB covered). We record it as a miss.

   POINT-IN-TIME NOTE — WHY `as_of` IS A COLUMN
   This endpoint returns only TODAY's estimates; there is no history. Estimates
   revise, so a snapshot taken now must never be treated as what was knowable in
   the past. Every row therefore carries BOTH the period it forecasts
   (`period_end`) and the date we learned it (`as_of`). History builds forward as
   monthly snapshots accumulate. The ingest for this table MERGES and must never
   replace per (pk, metric) the way valuation_ratios does — a replace would
   delete every prior snapshot on the first run, which is exactly the class of
   silent data loss fixed on 2026-09-07 (commit 0b0ecce).

   RUN: open a logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.
        Leave the tab open. Click "Allow" if Chrome asks about multiple files.
        ~1,900 stocks at CONC 4 ≈ 25-35 min (one request per stock, but pages are
        large — 75KB uncovered, up to 600KB covered).

   OUTPUT (Downloads), cols = pk,metric,period_end,as_of,value :
     tl_forecaster_estimates_partNN.csv
   Plus a one-row-per-stock coverage ledger, so a thin harvest is visible rather
   than inferred:
     tl_forecaster_coverage_partNN.csv   (pk,as_of,covered,annual_rows,http_status)
============================================================================ */
(async () => {
  // ----------------------------- CONFIG -------------------------------------
  const QUERY   = 'mcapq > 500';   // same universe as the DVM pull (~1,849-1,910 stocks)
  const CONC    = 4;               // matches trendlyne_dvm_harvester.js (measured; 6 -> ~8% 429s)
  const FLUSH_ROWS = 2_000_000;    // rows per downloaded part

  // Which RANGE_ESTIMATES metrics to keep, and the prefix each gets in the CSV.
  // The parser is generic — add a metric here and it is harvested, no other change.
  const METRICS = { EPS: 'EPS', TARGET_PRICE: 'TP' };

  // Fields to emit per estimate row. NUMBER_OF_ANALYSTS is not decoration: with
  // coverage this thin, a 1-analyst estimate and a 25-analyst estimate must be
  // distinguishable downstream or the factor inherits noise it cannot see.
  const FIELDS = ['AVG', 'HIGH', 'LOW', 'MEDIAN', 'ACTUAL', 'NUMBER_OF_ANALYSTS'];
  const FIELD_SUFFIX = { AVG: 'AVG', HIGH: 'HIGH', LOW: 'LOW', MEDIAN: 'MEDIAN',
                         ACTUAL: 'ACTUAL', NUMBER_OF_ANALYSTS: 'N' };

  // Quarterly estimates exist too. Off by default for the same reason leg1-lite
  // gates growth_quality: the engine reads annual, and quarterly triples the rows
  // for nothing. Flip when a strategy actually asks for it.
  const FETCH_QUARTERLY = false;

  // 'download' writes CSV parts to Downloads (the normal human-run monthly path).
  // 'memory' keeps them in window.__WF_FORECASTER.est / .cov instead, for a run
  // driven from a tool session that reads the rows out and writes them serverside
  // directly — no Downloads round-trip, no "allow multiple downloads" prompt.
  const EMIT = 'download';
  // --------------------------------------------------------------------------

  const csrf  = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const IST = 19800000;
  const AS_OF = new Date(Date.now() + IST).toISOString().slice(0, 10);

  if (!csrf) {
    alert('No csrftoken cookie — you are not logged in to trendlyne.com. Run trendlyne_preflight.js first.');
    return;
  }

  // progress panel
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:380px;'
    + 'padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Forecaster (consensus estimates)</b>'
    + '<div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  let stopped = false;
  const stop = document.createElement('button');
  stop.textContent = 'Stop';
  stop.style.cssText = 'margin-top:8px;padding:4px 10px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer';
  stop.onclick = () => { stopped = true; stop.textContent = 'stopping…'; };
  box.appendChild(stop);

  const download = (name, text) => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
    const a = document.createElement('a'); a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 15000);
  };

  // 1) stock list (same screener call as the DVM harvester and leg1-lite)
  log('fetching stock list…');
  const aio = page => fetch('https://trendlyne.com/fundamentals/api/screener-v2/try-aio/', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: JSON.stringify({ perPageCount: 100, groupType: 'all', groupName: 'all', sortBy: 'mcapq', order: 'DESC', query: QUERY, pageNumber: page })
  }).then(r => r.json());
  let stocks = [], col = {};
  for (let p = 1; p <= 80; p++) {
    const b = (await aio(p)).body; if (!b || !b.tableData) break;
    if (p === 1) b.tableHeaders.forEach((h, i) => col[h.unique_name] = i);
    for (const row of b.tableData) stocks.push(row[col.stock_id]);
    if (!b.isNextPage) break; await sleep(120);
  }
  stocks = [...new Set(stocks.filter(Boolean))];
  if (stocks.length < 1000) {
    log(`<b style="color:#f87171">ABORT</b> · screener returned only ${stocks.length} stocks `
      + `(expected ~1,849). Truncated list — re-run rather than ingest a partial harvest.`);
    return;
  }
  log(`${stocks.length} stocks · ${Object.keys(METRICS).length} metric groups · 1 request each`);

  // 2) buffers. Progress + rows are published on window so a driving session can
  // read them without waiting on a single long-running call.
  const P = window.__WF_FORECASTER = { total: stocks.length, done: 0, covered: 0,
    rows: 0, errs: 0, throttled: 0, finished: false, as_of: AS_OF, est: [], cov: [] };
  let estBuf = ['pk,metric,period_end,as_of,value'], estPart = 1, estRows = 0;
  let covBuf = ['pk,as_of,covered,annual_rows,http_status'], covPart = 1, covRows = 0;
  const flushEst = () => {
    if (!estRows) return;
    if (EMIT === 'memory') { P.est.push(estBuf.join('\n')); }
    else download(`tl_forecaster_estimates_part${String(estPart).padStart(2, '0')}.csv`, estBuf.join('\n') + '\n');
    estPart++; estBuf = ['pk,metric,period_end,as_of,value']; estRows = 0;
  };
  const flushCov = () => {
    if (!covRows) return;
    if (EMIT === 'memory') { P.cov.push(covBuf.join('\n')); }
    else download(`tl_forecaster_coverage_part${String(covPart).padStart(2, '0')}.csv`, covBuf.join('\n') + '\n');
    covPart++; covBuf = ['pk,as_of,covered,annual_rows,http_status']; covRows = 0;
  };

  // 3) fetch + parse one stock
  let throttled = 0;   // surfaced in the panel: if this climbs, CONC is still too high
  const decode = s => new DOMParser().parseFromString('<!doctype html><body>' + s, 'text/html').body.textContent;

  async function consensus(pk) {
    for (let a = 0; a < 3; a++) {
      try {
        const r = await fetch(`https://trendlyne.com/equity/consensus-estimates/${pk}/x/x/`,
                              { credentials: 'include' });
        if (r.status === 429) { throttled++; await sleep(3000 * (a + 1)); continue; }
        if (r.status !== 200) return { status: r.status, json: null };
        const h = await r.text();
        const m = h.match(/data-consensusjson=(["'])([\s\S]*?)\1/);
        if (!m) return { status: 200, json: null };          // page shape changed
        return { status: 200, json: JSON.parse(decode(m[2])) };
      } catch (e) { await sleep(800); }
    }
    return { status: 0, json: null };
  }

  let idx = 0, done = 0, errs = 0, covered = 0, totalRows = 0; const t0 = Date.now();
  async function worker() {
    while (!stopped) {
      const i = idx++; if (i >= stocks.length) break;
      const pk = stocks[i];
      const { status, json } = await consensus(pk);
      if (status !== 200) { errs++; covBuf.push(`${pk},${AS_OF},0,0,${status}`); covRows++; done++; continue; }

      const re = (json && json.RANGE_ESTIMATES) || {};
      let annualRows = 0;
      for (const key in METRICS) {
        const node = re[key]; if (!node) continue;
        const buckets = FETCH_QUARTERLY ? ['ANNUAL', 'QUARTER'] : ['ANNUAL'];
        for (const bucket of buckets) {
          const arr = node[bucket]; if (!Array.isArray(arr)) continue;
          for (const row of arr) {
            const pe = row.qtr_end_date; if (!pe) continue;
            const tag = bucket === 'QUARTER' ? METRICS[key] + 'Q' : METRICS[key];
            for (const f of FIELDS) {
              const v = row[f];
              if (v === null || v === undefined || v === '') continue;
              estBuf.push(`${pk},${tag}_${FIELD_SUFFIX[f]},${pe},${AS_OF},${v}`);
              estRows++; totalRows++;
            }
            if (bucket === 'ANNUAL') annualRows++;
          }
        }
      }
      // an uncovered stock is a legitimate 200 with an empty RANGE_ESTIMATES —
      // record it, so a thin harvest is measured rather than inferred
      const isCov = annualRows > 0 ? 1 : 0;
      if (isCov) covered++;
      covBuf.push(`${pk},${AS_OF},${isCov},${annualRows},200`); covRows++;
      if (estRows >= FLUSH_ROWS) flushEst();

      done++;
      P.done = done; P.covered = covered; P.rows = totalRows; P.errs = errs; P.throttled = throttled;
      if (done % 10 === 0 || done === stocks.length) {
        const rate = done / ((Date.now() - t0) / 1000);
        const eta = Math.round((stocks.length - done) / Math.max(rate, 0.01) / 60);
        P.eta_min = eta;
        log(`stocks ${done}/${stocks.length} · covered ${covered} (${Math.round(100 * covered / done)}%) · `
          + `rows ${totalRows.toLocaleString()} · errs ${errs} · 429s ${throttled} · ETA ~${eta}m`);
      }
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  flushEst(); flushCov();
  P.finished = true;
  log(`DONE · ${done} stocks · covered ${covered} (${Math.round(100 * covered / Math.max(done, 1))}%) · `
    + `${totalRows.toLocaleString()} rows · parts est(${estPart - 1}) cov(${covPart - 1}) · `
    + `errs ${errs} · 429s ${throttled}`);
  stop.textContent = 'Done ✓'; stop.disabled = true;
})();
