/* ============================================================================
   Trendlyne DVM History Harvester  —  Windfall Labs
   ----------------------------------------------------------------------------
   WHAT IT DOES
     Downloads the full Durability / Valuation / Momentum score *history*
     (back to ~2016, the "All" range) for every stock in your screener
     universe, straight from Trendlyne's internal API — no clicking.

   HOW TO RUN
     1. Open any trendlyne.com page while LOGGED IN (e.g. your screener tab).
     2. Press F12  ->  click the "Console" tab.
     3. Paste this entire file, press Enter. Leave the tab open (~1 hour).
     4. When the first file downloads, Chrome shows a chip asking to
        "Allow trendlyne.com to download multiple files" -> click ALLOW (once).

   OUTPUT  (saved to your Downloads folder)
     tl_stocks.csv                pk, nsecode, name, mcap, d_now, v_now, m_now
     tl_dvm_history_partNN.csv    pk, score, date, value     [LONG format]
        score codes:  d = durability, v = valuation, m = momentum
        date is IST (YYYY-MM-DD); value is the score 0-100
     -> load every tl_dvm_history_part*.csv into one DB table; join on pk.

   NOTES
     - QUERY below = your universe filter. 'mcapq > 500' = the ~1,849 stocks.
       Change it to widen/narrow; re-running starts fresh.
     - If interrupted, the parts already downloaded are kept; just re-run.
============================================================================ */
(async () => {
  // ----------------------------- CONFIG -------------------------------------
  const QUERY      = 'mcapq > 500';   // screener filter (market cap in Cr)
  const CONC       = 4;               // was 6: measured ~8% of fetches 429'd out on 2026-09-07
  const FLUSH_ROWS = 2_000_000;       // rows per downloaded history part (~48MB)
  const PARAMS = [['d','TL_DURABILITY_METRIC'],
                  ['v','TL_VALUATION_METRIC'],
                  ['m','abs_score']];
  // --------------------------------------------------------------------------

  const csrf  = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const IST   = 19800000; // +5:30 in ms (India has no DST)
  const dstr  = ms => new Date(ms + IST).toISOString().slice(0, 10);

  // --------------------------- progress panel -------------------------------
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:330px;'
    + 'padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui,sans-serif;'
    + 'border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · DVM Harvester</b><div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  let stopped = false;
  const stop = document.createElement('button');
  stop.textContent = 'Stop';
  stop.style.cssText = 'margin-top:8px;padding:4px 10px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer';
  stop.onclick = () => { stopped = true; stop.textContent = 'stopping…'; };
  box.appendChild(stop);

  // ----------------------------- download -----------------------------------
  const download = (name, text) => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 15000);
  };

  // ------------------- 1) build stock list from screener --------------------
  log('fetching stock list…');
  const aio = page => fetch('https://trendlyne.com/fundamentals/api/screener-v2/try-aio/', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    body: JSON.stringify({ perPageCount: 100, groupType: 'all', groupName: 'all',
                           sortBy: 'mcapq', order: 'DESC', query: QUERY, pageNumber: page })
  }).then(r => r.json());

  let stocks = [], col = {};
  for (let p = 1; p <= 80; p++) {
    const b = (await aio(p)).body;
    if (!b || !b.tableData) break;
    if (p === 1) b.tableHeaders.forEach((h, i) => col[h.unique_name] = i);
    for (const row of b.tableData)
      stocks.push({ pk: row[col.stock_id], sym: row[col.NSEcode] || '',
                    name: (row[col.shortname] || '').trim(), mcap: row[col.mcapq],
                    d: row[col.d_value], v: row[col.v_value], m: row[col.m_value] });
    if (!b.isNextPage) break;
    await sleep(120);
  }
  const seen = new Set();
  stocks = stocks.filter(s => s.pk && !seen.has(s.pk) && seen.add(s.pk));

  download('tl_stocks.csv', 'pk,nsecode,name,mcap,d_now,v_now,m_now\n' +
    stocks.map(s => [s.pk, s.sym, '"' + String(s.name).replace(/"/g, '""') + '"',
                     s.mcap, s.d, s.v, s.m].join(',')).join('\n') + '\n');

  // ------------------------ 2) fetch DVM history ----------------------------
  async function hist(pk, param, attempts = 3, base = 3000) {
    for (let a = 0; a < attempts; a++) {
      try {
        const r = await fetch(`https://trendlyne.com/equity/all-param-history/${pk}/${param}/`,
                              { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (r.status === 429) { await sleep(base * (a + 1)); continue; }   // backoff
        if (r.status !== 200) return { err: r.status, data: [] };
        return { err: 0, data: JSON.parse((await r.json()).chartData).series[0].data };
      } catch (e) { await sleep(1000); }
    }
    return { err: 'retry', data: [] };
  }

  let buf = ['pk,score,date,value'], bufRows = 0, part = 1, totalRows = 0, done = 0, errs = 0;
  const misses = [];   // every (pk,param) that exhausted its retries - swept before writing
  const seenScores = {};   // pk -> Set of score codes that returned at least one row
  const t0 = Date.now();
  const flush = () => {
    if (!bufRows) return;
    download(`tl_dvm_history_part${String(part).padStart(2, '0')}.csv`, buf.join('\n') + '\n');
    part++; buf = ['pk,score,date,value']; bufRows = 0;
  };

  let idx = 0;
  async function worker() {
    while (!stopped) {
      const i = idx++;
      if (i >= stocks.length) break;
      const s = stocks[i];
      for (const [code, param] of PARAMS) {
        const r = await hist(s.pk, param);
        if (r.err) { errs++; misses.push({ pk: s.pk, sym: s.sym, code, param, err: r.err }); continue; }
        if (r.data.length) (seenScores[s.pk] = seenScores[s.pk] || new Set()).add(code);
        else (seenScores[s.pk] = seenScores[s.pk] || new Set());
        for (const [ms, val] of r.data) { buf.push(`${s.pk},${code},${dstr(ms)},${val}`); bufRows++; totalRows++; }
      }
      done++;
      if (bufRows >= FLUSH_ROWS) flush();
      if (done % 20 === 0 || done === stocks.length) {
        const rate = done / ((Date.now() - t0) / 1000);
        const eta = Math.round((stocks.length - done) / Math.max(rate, 0.01) / 60);
        log(`stocks ${done}/${stocks.length} · rows ${(totalRows / 1e6).toFixed(2)}M · `
          + `parts ${part - 1} · errs ${errs} · ETA ~${eta}m`);
      }
    }
  }

  // How many stocks actually ended with all three scores? This is NOT the same as "no fetch
  // failures": Trendlyne returns HTTP 200 with an empty series for stocks it does not score
  // (REITs, InvITs, many recent listings), which never counts as a miss. 2026-09-07 pull 2:
  // 0 fetch failures, yet 182 stocks had <3 scores - 172 of them genuinely unscored.
  function scoreCoverage() {
    const n3 = Object.values(seenScores).filter(set => set.size === 3).length;
    const tot = Object.keys(seenScores).length;
    const short = tot - n3;
    return short
      ? `<b>${n3}/${tot}</b> stocks have all 3 scores; ${short} have fewer `
        + `(Trendlyne does not score every stock - check tl_stocks.csv d_now/v_now/m_now)`
      : `<b>${n3}/${tot}</b> stocks have all 3 scores`;
  }

  await Promise.all(Array.from({ length: CONC }, worker));

  // ---------------------- recovery sweep (added 2026-09-07) -----------------
  // A (pk,param) that exhausted its retries used to be counted in `errs` and then
  // DROPPED. The stock still wrote its surviving scores, so it looked populated
  // while silently carrying 1 or 2 of 3. Measured on the 2026-09-07 refresh:
  // 24 stocks landed with zero rows and 62 MORE with a single param - including
  // GODREJCP, VOLTAS, MOTHERSON, JSWENERGY. Because the ingest replaces a pk's
  // rows wholesale, those partials would have DELETED real history (the ingest's
  // shrink guard caught it). This sweeps every miss once, slowly, before writing.
  let still = [];
  if (misses.length && !stopped) {
    let sdone = 0, srec = 0;
    for (const m of misses) {
      if (stopped) break;
      const r = await hist(m.pk, m.param, 6, 5000);   // patient: 6 tries, 5s -> 30s
      sdone++;
      if (r.err) still.push(m);
      else {
        srec++;
        if (r.data.length) (seenScores[m.pk] = seenScores[m.pk] || new Set()).add(m.code);
        for (const [ms, val] of r.data) { buf.push(`${m.pk},${m.code},${dstr(ms)},${val}`); bufRows++; totalRows++; }
        if (bufRows >= FLUSH_ROWS) flush();
      }
      if (sdone % 5 === 0 || sdone === misses.length)
        log(`recovery sweep ${sdone}/${misses.length} · recovered ${srec} · still missing ${still.length}`);
      await sleep(400);
    }
  }

  flush();

  // Anything still missing is now VISIBLE, not a number in `errs`.
  if (still.length) {
    const NL = String.fromCharCode(10);
    download('tl_dvm_misses.csv', 'pk,sym,score,err' + NL
      + still.map(m => `${m.pk},${m.sym},${m.code},${m.err}`).join(NL) + NL);
    const byPk = {};
    for (const m of still) (byPk[m.sym || m.pk] = byPk[m.sym || m.pk] || []).push(m.code);
    const names = Object.keys(byPk).slice(0, 8).map(k => `${k}(${byPk[k].join('')})`).join(', ');
    log(`DONE · ${done} stocks · ${(totalRows / 1e6).toFixed(2)}M rows · ${part - 1} file(s)<br>`
      + `<b style="color:#fca5a5">${still.length} score(s) across ${Object.keys(byPk).length} stock(s) still missing</b>`
      + `<br>${names}${Object.keys(byPk).length > 8 ? ' ...' : ''}<br>-> see tl_dvm_misses.csv`
      + `<br>${scoreCoverage()}`);
  } else {
    log(`DONE · ${done} stocks · ${(totalRows / 1e6).toFixed(2)}M rows · `
      + `${part - 1} history file(s) + tl_stocks.csv<br>`
      + `<b style="color:#86efac">no fetch failures</b>`
      + (misses.length ? ` (sweep refilled ${misses.length})` : '')
      + `<br>${scoreCoverage()}`);
  }
  stop.textContent = 'Done ✓'; stop.disabled = true;
})();
