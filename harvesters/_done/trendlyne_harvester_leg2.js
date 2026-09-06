/* ============================================================================
   Trendlyne Leg-2 Harvester  —  Windfall Labs
   ----------------------------------------------------------------------------
   FULL annual financial statements (CONSOLIDATED), 11 years (Mar 2016→2026):
   P&L, Balance Sheet, Cash Flow, Ratios — every line item, incl. bank-specific.

   Uses the BULK endpoint get-fundamental_results-v2 (1 dump per stock) instead
   of per-metric, so it's ~2 requests/stock (~20 min) not ~150k requests.

   RUN: logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.
        Leave open ~20-30 min. Click "Allow" on the multiple-downloads chip.

   OUTPUT (Downloads), long format cols = pk,metric,date,value :
     tl_pnl_annual_partNN.csv        (Income Statement line items)
     tl_balance_sheet_partNN.csv     (Balance Sheet line items)
     tl_cashflow_partNN.csv          (Cash Flow line items)
     tl_ratios_annual_partNN.csv     (Financial Ratios)
     tl_financials_other_partNN.csv  (uncategorised line items)
     tl_annual_metadata.csv          (code -> name,cat1,cat2,unit) = data dictionary
   `date` = fiscal period-end (e.g. Mar 2026 -> 2026-03-31). TTM is skipped.
   `pk` joins to trendlyne_data/_reference/tl_stocks.csv.
============================================================================ */
(async () => {
  // ----------------------------- CONFIG -------------------------------------
  const QUERY      = 'mcapq > 500';
  const CONC       = 6;
  const FLUSH_ROWS = 2_000_000;
  const TABLE_OF_CAT1 = {
    'Income Statement': 'pnl_annual',
    'Balance Sheet':    'balance_sheet',
    'Cash Flow':        'cashflow',
    'Financial Ratios': 'ratios_annual',
  };
  const OTHER = 'financials_other';
  // --------------------------------------------------------------------------

  const csrf  = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const MONTHS = { Jan:0,Feb:1,Mar:2,Apr:3,May:4,Jun:5,Jul:6,Aug:7,Sep:8,Oct:9,Nov:10,Dec:11 };
  const periodDate = label => {                       // "Mar 2026" -> "2026-03-31"; "TTM" -> null
    const m = String(label).match(/^([A-Za-z]{3})\s+(\d{4})$/); if (!m) return null;
    const mo = MONTHS[m[1]]; if (mo === undefined) return null;
    return new Date(Date.UTC(+m[2], mo + 1, 0)).toISOString().slice(0, 10);
  };
  const pad = n => String(n).padStart(2, '0');
  const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';

  // progress UI
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:350px;padding:14px 16px;'
    + 'background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Leg-2 Harvester (annual)</b><div id="wfp" style="margin-top:6px">starting…</div>';
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

  // 1) stock list (pk + NSE symbol — symbol needed for the token)
  log('fetching stock list…');
  const aio = page => fetch('https://trendlyne.com/fundamentals/api/screener-v2/try-aio/', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: JSON.stringify({ perPageCount: 100, groupType: 'all', groupName: 'all', sortBy: 'mcapq', order: 'DESC', query: QUERY, pageNumber: page })
  }).then(r => r.json());
  let stocks = [], col = {}, seen = new Set();
  for (let p = 1; p <= 80; p++) {
    const b = (await aio(p)).body; if (!b || !b.tableData) break;
    if (p === 1) b.tableHeaders.forEach((h, i) => col[h.unique_name] = i);
    for (const row of b.tableData) {
      const pk = row[col.stock_id]; if (pk && !seen.has(pk)) { seen.add(pk); stocks.push({ pk, sym: row[col.NSEcode] || '' }); }
    }
    if (!b.isNextPage) break; await sleep(120);
  }

  // 2) per-stock: token -> bulk dump -> route annual line items by cat1
  async function getTok(pk, sym) {
    if (!sym) return null;
    try {
      const s = await (await fetch('https://trendlyne.com/equity/api/ac_snames/price/?term=' + encodeURIComponent(sym),
                                   { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } })).json();
      const m = (Array.isArray(s) ? s : []).find(x => x.k === pk);
      const mm = m && m.ohlc_url && m.ohlc_url.match(/web\/ohlc\/\d+\/([^\/]+)\//);
      return mm ? mm[1] : null;
    } catch (e) { return null; }
  }
  async function getDump(pk, tok) {
    for (let a = 0; a < 3; a++) {
      try {
        const r = await fetch(`https://trendlyne.com/fundamentals/get-fundamental_results-v2/${pk}/${tok}/`,
                              { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (r.status === 429) { await sleep(3000 * (a + 1)); continue; }
        if (r.status !== 200) return null;
        return (await r.json()).body;
      } catch (e) { await sleep(800); }
    }
    return null;
  }

  const buf = {}, parts = {}, rows = {};
  const ensure = t => { if (!buf[t]) { buf[t] = ['pk,metric,date,value']; parts[t] = 1; rows[t] = 0; } };
  const flush = t => { if (!rows[t]) return; download(`tl_${t}_part${pad(parts[t])}.csv`, buf[t].join('\n') + '\n'); parts[t]++; buf[t] = ['pk,metric,date,value']; rows[t] = 0; };
  const meta = {};   // code -> {name,cat1,cat2,unit}

  let idx = 0, done = 0, noTok = 0, errs = 0, totalRows = 0; const t0 = Date.now();
  async function worker() {
    while (!stopped) {
      const i = idx++; if (i >= stocks.length) break;
      const { pk, sym } = stocks[i];
      const tok = await getTok(pk, sym);
      if (!tok) { noTok++; done++; continue; }
      const body = await getDump(pk, tok);
      if (!body || !body.annualDataDump) { errs++; done++; continue; }
      const pm = body.parameterMetadata || {};
      for (const c in pm) { const md = pm[c]; if (md && !meta[c]) meta[c] = { name: md.name, cat1: md.cat1, cat2: md.cat2, unit: md.unit }; }
      const cons = body.annualDataDump.consolidated;
      const dumpA = (cons && Object.keys(cons).length) ? cons : body.annualDataDump.standalone;
      if (dumpA) {
        for (const period in dumpA) {
          const date = periodDate(period); if (!date) continue;     // skips TTM
          const obj = dumpA[period];
          for (const code in obj) {
            const v = obj[code];
            if (typeof v !== 'number' || !isFinite(v)) continue;
            const cat1 = pm[code] && pm[code].cat1;
            const t = TABLE_OF_CAT1[cat1] || OTHER;
            ensure(t); buf[t].push(`${pk},${code},${date},${v}`); rows[t]++; totalRows++;
            if (rows[t] >= FLUSH_ROWS) flush(t);
          }
        }
      }
      done++;
      if (done % 25 === 0 || done === stocks.length) {
        const rate = done / ((Date.now() - t0) / 1000);
        const eta = Math.round((stocks.length - done) / Math.max(rate, 0.01) / 60);
        log(`stocks ${done}/${stocks.length} · rows ${(totalRows / 1e6).toFixed(2)}M · noToken ${noTok} · errs ${errs} · ETA ~${eta}m`);
      }
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  for (const t in buf) flush(t);

  // metadata dictionary
  const md = ['code,name,cat1,cat2,unit'];
  for (const c of Object.keys(meta).sort()) md.push([c, q(meta[c].name), q(meta[c].cat1), q(meta[c].cat2), q(meta[c].unit)].join(','));
  download('tl_annual_metadata.csv', md.join('\n') + '\n');

  log(`DONE · ${done} stocks · ${(totalRows / 1e6).toFixed(2)}M rows · noToken ${noTok} · errs ${errs} · tables: ${Object.keys(buf).join(', ')}`);
  stop.textContent = 'Done ✓'; stop.disabled = true;
})();
