/* ============================================================================
   Trendlyne Leg-1 Harvester (LITE)  —  Windfall Labs
   ----------------------------------------------------------------------------
   The monthly-refresh version of leg1: fetches ONLY the six metrics the engine
   actually reads, at the concurrency the other harvesters were tuned to.

   WHY THIS EXISTS (2026-09-07, iter-172)
   The full leg1 fetches 25 metric codes x ~1,849 stocks = ~46,000 requests and
   takes ~2.5 hours. Of those 25 codes the engine reads exactly SIX:

     valuation_ratios : PE_TTM, PEG_TTM, PBV_A
         -> the tl_pe / tl_peg / tl_pbv factors, and the whole reason the monthly
            refresh needs leg1 at all (to-do #849/#851). Without them the table
            freezes and a live paper book silently ranks on stale multiples.
     growth_quality   : PITROSKI_F, NP_TTM_GROWTH, SR_TTM_GROWTH
         -> tl_piotroski / tl_np_growth / tl_rev_growth, per _RAW_FUND in
            windfall/data/trendlyne_store.py.

   The other 19 codes populate `pnl_quarterly` and `ownership`, which NOTHING in
   the engine reads today:
     - pnl_quarterly (14 codes) - the annual equivalents the engine does use
       (EPS_A, ROE_A, ROCE_A ...) come from `ratios_annual` / `pnl_annual`, which
       leg2 fetches, not leg1.
     - ownership (3 codes: FIIHOLD/MFHOLD/INSTIHOLD) - the shareholding features
       (tl_pledge/tl_fii/tl_dii) read `shareholding_summary`, which leg1_5
       fetches, not this.

   6 codes instead of 25 = ~11,000 requests instead of ~46,000: roughly 35-40
   minutes instead of 150.

   CONC is 4, not 8. The DVM harvester was dialled 6 -> 4 on 2026-09-07 after
   measuring ~8% of fetches getting 429'd; leg1 never received that fix because
   it was parked in _done/. Past the server's limit, more concurrency is SLOWER,
   not faster - every 429 costs a 3s/6s/9s backoff before the retry.

   NEED THE OTHER 19 CODES? Run `trendlyne_harvester_leg1.js` (the full version,
   kept alongside this one). Nothing reads them today, but a future strategy
   might, and the tables cost nothing to hold.

   RUN: open a logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.
        Leave the tab open. Click "Allow" if Chrome asks about multiple files.

   OUTPUT (Downloads), long format, cols = pk,metric,date,value :
     tl_valuation_ratios_partNN.csv   (daily)
     tl_growth_quality_partNN.csv     (quarterly)
   Both are ingested by backend/scripts/ingest_refresh.py, replaced per
   (pk, metric) so a partial harvest cannot delete the metrics it omits.
============================================================================ */
(async () => {
  // ----------------------------- CONFIG -------------------------------------
  const QUERY      = 'mcapq > 500';   // same universe as the DVM pull (~1,849 stocks)
  const CONC       = 4;               // matches trendlyne_dvm_harvester.js (measured; 6 -> ~8% 429s)
  const FLUSH_ROWS = 2_000_000;       // rows per downloaded part
  const TABLES = {
    valuation_ratios: ['PE_TTM', 'PEG_TTM', 'PBV_A'],
    growth_quality:   ['PITROSKI_F', 'NP_TTM_GROWTH', 'SR_TTM_GROWTH'],
  };
  // --------------------------------------------------------------------------

  const codeTable = {}, allCodes = [];
  for (const t in TABLES) for (const c of TABLES[t]) { codeTable[c] = t; allCodes.push(c); }

  const csrf  = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const IST = 19800000, dstr = ms => new Date(ms + IST).toISOString().slice(0, 10);

  // progress panel
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:360px;'
    + 'padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Leg-1 LITE (6 metrics)</b><div id="wfp" style="margin-top:6px">starting…</div>';
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

  // 1) stock list (same screener call as the DVM harvester)
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
  log(`${stocks.length} stocks · ${allCodes.length} metrics · ~${(stocks.length * allCodes.length / 1000).toFixed(1)}k requests`);

  // 2) per-table buffers
  const buf = {}, parts = {}, rows = {};
  for (const t in TABLES) { buf[t] = ['pk,metric,date,value']; parts[t] = 1; rows[t] = 0; }
  const flush = t => {
    if (!rows[t]) return;
    download(`tl_${t}_part${String(parts[t]).padStart(2, '0')}.csv`, buf[t].join('\n') + '\n');
    parts[t]++; buf[t] = ['pk,metric,date,value']; rows[t] = 0;
  };

  let throttled = 0;   // surfaced in the panel: if this climbs, CONC is still too high
  async function hist(pk, code) {
    for (let a = 0; a < 3; a++) {
      try {
        const r = await fetch(`https://trendlyne.com/equity/all-param-history/${pk}/${encodeURIComponent(code)}/`,
                              { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (r.status === 429) { throttled++; await sleep(3000 * (a + 1)); continue; }
        if (r.status !== 200) return null;
        return JSON.parse((await r.json()).chartData).series[0].data;
      } catch (e) { await sleep(800); }
    }
    return null;
  }

  let idx = 0, done = 0, errs = 0, totalRows = 0; const t0 = Date.now();
  async function worker() {
    while (!stopped) {
      const i = idx++; if (i >= stocks.length) break;
      const pk = stocks[i];
      for (const code of allCodes) {
        const d = await hist(pk, code);
        if (!d) { errs++; continue; }
        const t = codeTable[code];
        for (const [ms, v] of d) { buf[t].push(`${pk},${code},${dstr(ms)},${v}`); rows[t]++; totalRows++; }
        if (rows[t] >= FLUSH_ROWS) flush(t);
      }
      done++;
      if (done % 10 === 0 || done === stocks.length) {
        const rate = done / ((Date.now() - t0) / 1000);
        const eta = Math.round((stocks.length - done) / Math.max(rate, 0.01) / 60);
        log(`stocks ${done}/${stocks.length} · rows ${(totalRows / 1e6).toFixed(2)}M · `
          + `errs ${errs} · 429s ${throttled} · ETA ~${eta}m`);
      }
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  for (const t in TABLES) flush(t);
  log(`DONE · ${done} stocks · ${(totalRows / 1e6).toFixed(2)}M rows · `
    + Object.keys(TABLES).map(t => `${t}(${parts[t] - 1})`).join(' · ')
    + ` · errs ${errs} · 429s ${throttled}`);
  stop.textContent = 'Done ✓'; stop.disabled = true;
})();
