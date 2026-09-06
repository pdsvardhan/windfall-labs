/* ============================================================================
   Trendlyne Leg-1 Harvester  —  Windfall Labs
   ----------------------------------------------------------------------------
   Daily valuation ratios + quarterly P&L / growth / ownership (CONSOLIDATED),
   full history (~2016→now), via the same all-param-history endpoint as DVM.

   RUN: open a logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.
        Leave the tab open (~1.5-2 hrs). Click "Allow" if Chrome asks to
        download multiple files.

   OUTPUT (Downloads), long format, cols = pk,metric,date,value :
     tl_valuation_ratios_partNN.csv   (daily)
     tl_pnl_quarterly_partNN.csv      (quarterly)
     tl_growth_quality_partNN.csv     (quarterly)
     tl_ownership_partNN.csv          (quarterly)
   `metric` = Trendlyne code (see trendlyne_data/DATA_DICTIONARY.md).
   `pk` joins to trendlyne_data/_reference/tl_stocks.csv.

   NOTE: this is ~46k requests; it WILL take ~1.5-2 hrs. Don't close the tab.
============================================================================ */
(async () => {
  // ----------------------------- CONFIG -------------------------------------
  const QUERY      = 'mcapq > 500';   // same universe as the DVM pull (1,849 stocks)
  const CONC       = 8;               // parallel stock-workers (≈8 requests in flight)
  const FLUSH_ROWS = 2_000_000;       // rows per downloaded part
  const TABLES = {
    valuation_ratios: ['PE_TTM','PEG_TTM','PBV_A'],
    pnl_quarterly:    ['TOTAL_SR_Q','SR_Q','OperatingIncome_Q','OI_Q','OP_Q','OPMPCT_Q',
                       'DEP_Q','INT_Q','PBT_Q','TAX_Q','NP_Q','EPS_adj_Q','NP_TTM','EPS_TTM'],
    growth_quality:   ['REV4Q_Q','SR_TTM_GROWTH','NP_Q_GROWTH','NP_TTM_GROWTH','PITROSKI_F'],
    ownership:        ['FIIHOLD','MFHOLD','INSTIHOLD'],
  };
  // --------------------------------------------------------------------------

  const codeTable = {}, allCodes = [];
  for (const t in TABLES) for (const c of TABLES[t]) { codeTable[c] = t; allCodes.push(c); }

  const csrf  = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const IST = 19800000, dstr = ms => new Date(ms + IST).toISOString().slice(0, 10);

  // progress panel
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:350px;'
    + 'padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Leg-1 Harvester</b><div id="wfp" style="margin-top:6px">starting…</div>';
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

  // 1) stock list (same screener call as DVM harvester)
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

  // 2) per-table buffers
  const buf = {}, parts = {}, rows = {};
  for (const t in TABLES) { buf[t] = ['pk,metric,date,value']; parts[t] = 1; rows[t] = 0; }
  const flush = t => {
    if (!rows[t]) return;
    download(`tl_${t}_part${String(parts[t]).padStart(2, '0')}.csv`, buf[t].join('\n') + '\n');
    parts[t]++; buf[t] = ['pk,metric,date,value']; rows[t] = 0;
  };

  async function hist(pk, code) {
    for (let a = 0; a < 3; a++) {
      try {
        const r = await fetch(`https://trendlyne.com/equity/all-param-history/${pk}/${encodeURIComponent(code)}/`,
                              { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (r.status === 429) { await sleep(3000 * (a + 1)); continue; }
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
        log(`stocks ${done}/${stocks.length} · rows ${(totalRows / 1e6).toFixed(2)}M · errs ${errs} · ETA ~${eta}m`);
      }
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  for (const t in TABLES) flush(t);
  log(`DONE · ${done} stocks · ${(totalRows / 1e6).toFixed(2)}M rows · `
    + Object.keys(TABLES).map(t => `${t}(${parts[t] - 1})`).join(' · ') + ` · errs ${errs}`);
  stop.textContent = 'Done ✓'; stop.disabled = true;
})();
