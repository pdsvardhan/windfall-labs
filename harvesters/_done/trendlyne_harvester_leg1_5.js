/* ============================================================================
   Trendlyne Leg-1.5 Harvester  —  Windfall Labs
   ----------------------------------------------------------------------------
   The non-OHLCV, non-metric signals for small/mid-cap swing backtesting, by
   scraping two server-rendered pages per stock:
     • corporate-actions page  -> corporate actions + board-meeting/result dates + sector
     • share-holding page       -> promoter / pledge / DII / banks / insurance / public  (quarterly)

   RUN: logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.
        Leave open ~25-40 min. Click "Allow" on the multiple-downloads chip.

   OUTPUT (Downloads):
     tl_corporate_actions_partNN.csv   pk,action_type,ex_date,record_date,value,detail
        action_type: bonus|dividend|split|rights ; value = ratio "1:1" or amount (string)
     tl_result_dates_partNN.csv        pk,date,purpose        (board-meeting / results dates)
     tl_shareholding_summary_partNN.csv pk,category,date,pct  (Promoter/Pledged/DII/FII/MF/Public…, ~12 qtrs)
     tl_sector_map.csv                 pk,sector,industry     (one row per stock)
   `pk` joins to trendlyne_data/_reference/tl_stocks.csv. Dates = YYYY-MM-DD.

   DEPTH / SCOPE NOTES:
     - Corporate actions + result dates: full history shown on the page.
     - Shareholding summary: ~12 quarters (≈3 yrs) — that's what the "latest" page exposes.
       (Deeper history would need per-quarter dated pages = many more requests.)
     - Delivery % is NOT collected here: it is not available via Trendlyne's history
       endpoint (returns empty). Needs a separate source — left for later.
============================================================================ */
(async () => {
  const QUERY = 'mcapq > 500';
  const CONC  = 5;
  const FLUSH_ROWS = 2_000_000;

  const csrf  = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const MM = { Jan:'01',Feb:'02',Mar:'03',Apr:'04',May:'05',Jun:'06',Jul:'07',Aug:'08',Sep:'09',Oct:'10',Nov:'11',Dec:'12' };
  const dDMY = s => { const m = (s||'').match(/(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})/); return m ? `${m[3]}-${MM[m[2]]}-${String(m[1]).padStart(2,'0')}` : ''; };
  const dPeriod = s => {                                   // "Mar 2026" or "Oct 29, 2024"
    let m = s.match(/^([A-Za-z]{3})\s+(\d{4})$/); if (m) { const last = new Date(Date.UTC(+m[2], +MM[m[1]], 0)).getUTCDate(); return `${m[2]}-${MM[m[1]]}-${last}`; }
    m = s.match(/^([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})$/); if (m) return `${m[3]}-${MM[m[1]]}-${String(m[2]).padStart(2,'0')}`;
    return '';
  };
  const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';
  const cells = tr => [...tr.children].map(c => (c.textContent || '').trim().replace(/\s+/g, ' '));

  // UI
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:360px;padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Leg-1.5 Harvester</b><div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  let stopped = false;
  const stop = document.createElement('button');
  stop.textContent = 'Stop'; stop.style.cssText = 'margin-top:8px;padding:4px 10px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer';
  stop.onclick = () => { stopped = true; stop.textContent = 'stopping…'; };
  box.appendChild(stop);
  const download = (name, text) => { const url = URL.createObjectURL(new Blob([text], { type:'text/csv' })); const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 15000); };

  // 1) stock list (retry each page so a transient throttle can't truncate the list)
  log('fetching stock list…');
  const aio = async page => {
    for (let a = 0; a < 4; a++) {
      try {
        const r = await fetch('https://trendlyne.com/fundamentals/api/screener-v2/try-aio/', {
          method:'POST', credentials:'include',
          headers:{ 'Content-Type':'application/json', 'X-CSRFToken':csrf, 'X-Requested-With':'XMLHttpRequest' },
          body: JSON.stringify({ perPageCount:100, groupType:'all', groupName:'all', sortBy:'mcapq', order:'DESC', query:QUERY, pageNumber:page })
        });
        if (r.status === 429) { await sleep(3000 * (a + 1)); continue; }
        const j = await r.json();
        if (j && j.body && j.body.tableData) return j.body;
      } catch (e) {}
      await sleep(1200);
    }
    return null;
  };
  let stocks = [], col = {}, seen = new Set();
  for (let p = 1; p <= 80; p++) {
    const b = await aio(p);
    if (!b) { log('⚠ stock-list page ' + p + ' failed after retries'); break; }
    if (p === 1) b.tableHeaders.forEach((h, i) => col[h.unique_name] = i);
    for (const row of b.tableData) { const pk = row[col.stock_id], sym = row[col.NSEcode] || ''; if (pk && !seen.has(pk)) { seen.add(pk); stocks.push({ pk, sym }); } }
    if (!b.isNextPage) break; await sleep(200);
  }
  if (stocks.length < 1000) { log('⚠ ABORT: only ' + stocks.length + ' stocks — list looks truncated. Wait a moment and re-run.'); return; }
  log('stock list: ' + stocks.length + ' stocks — starting…');

  // output buffers
  const buf = {}, parts = {}, rows = {};
  const HEADERS = {
    corporate_actions: 'pk,action_type,ex_date,record_date,value,detail',
    result_dates: 'pk,date,purpose',
    shareholding_summary: 'pk,category,date,pct',
  };
  for (const t in HEADERS) { buf[t] = [HEADERS[t]]; parts[t] = 1; rows[t] = 0; }
  const flush = t => { if (!rows[t]) return; download(`tl_${t}_part${String(parts[t]).padStart(2,'0')}.csv`, buf[t].join('\n') + '\n'); parts[t]++; buf[t] = [HEADERS[t]]; rows[t] = 0; };
  const sectorRows = ['pk,sector,industry'];

  async function getHTML(u) { for (let a = 0; a < 3; a++) { try { const r = await fetch(u, { credentials:'include' }); if (r.status === 429) { await sleep(3000*(a+1)); continue; } if (r.status !== 200) return null; return await r.text(); } catch (e) { await sleep(800); } } return null; }

  function parseCorp(pk, html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    for (const t of doc.querySelectorAll('table')) {
      const H = [...t.querySelectorAll('thead th,thead td')].map(c => (c.textContent||'').trim()).join('|').toLowerCase();
      const trs = [...t.querySelectorAll('tbody tr')];
      if (/bonus ratio/.test(H)) trs.forEach(tr => { const c = cells(tr); push('corporate_actions', `${pk},bonus,${dDMY(c[0])},${dDMY(c[2])},${q(c[1])},${q('')}`); });
      else if (/dividend amount/.test(H)) trs.forEach(tr => { const c = cells(tr); push('corporate_actions', `${pk},dividend,${dDMY(c[0])},${dDMY(c[3])},${q(c[1])},${q((c[2]||'')+'/'+(c[4]||''))}`); });
      else if (/premium/.test(H)) trs.forEach(tr => { const c = cells(tr); push('corporate_actions', `${pk},rights,${dDMY(c[0])},${dDMY(c[4])},${q(c[1])},${q('fv='+(c[2]||'')+';prem='+(c[3]||''))}`); });
      else if (/face value/.test(H) && /split|old|new/.test(H)) trs.forEach(tr => { const c = cells(tr); push('corporate_actions', `${pk},split,${dDMY(c[0])},,${q(c.slice(1).join(' '))},${q('')}`); });
      else if (/\bpurpose\b/.test(H)) trs.forEach(tr => { const c = cells(tr); if (dDMY(c[0])) push('result_dates', `${pk},${dDMY(c[0])},${q(c[1])}`); });
    }
    const txt = doc.body ? doc.body.innerText : '';
    const sm = txt.match(/SECTOR\s*:\s*([^\n/]+?)\s*(?:INDUSTRY|\/)/i);
    const im = txt.match(/INDUSTRY\s*:\s*([^\n]+)/i);
    sectorRows.push(`${pk},${q(sm ? sm[1].trim() : '')},${q(im ? im[1].trim() : '')}`);
  }

  function parseHold(pk, html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    let tbl = null;
    for (const t of doc.querySelectorAll('table')) { if (/summary/i.test((t.querySelector('thead th,thead td')||{}).textContent || '')) { tbl = t; break; } }
    if (!tbl) return;
    const periods = [...tbl.querySelectorAll('thead th,thead td')].map(c => (c.textContent||'').trim().replace(/\s+/g,' ')).slice(1);
    for (const tr of tbl.querySelectorAll('tbody tr')) {
      const c = cells(tr); const label = c[0]; if (!label) continue;
      for (let i = 1; i < c.length && i <= periods.length; i++) {
        const v = c[i].replace(/[%,]/g, '');
        const d = dPeriod(periods[i-1]);
        if (d && v !== '' && v !== '-' && !isNaN(parseFloat(v))) push('shareholding_summary', `${pk},${q(label)},${d},${parseFloat(v)}`);
      }
    }
  }
  function push(t, line) { buf[t].push(line); rows[t]++; totalRows++; if (rows[t] >= FLUSH_ROWS) flush(t); }

  let idx = 0, done = 0, noSym = 0, errs = 0, totalRows = 0; const t0 = Date.now();
  async function worker() {
    while (!stopped) {
      const i = idx++; if (i >= stocks.length) break;
      const { pk, sym } = stocks[i];
      if (!sym) { noSym++; done++; continue; }
      const caHtml = await getHTML(`https://trendlyne.com/equity/corporate-actions/${encodeURIComponent(sym)}/${pk}/x/`);
      if (caHtml) { try { parseCorp(pk, caHtml); } catch (e) { errs++; } } else errs++;
      const shHtml = await getHTML(`https://trendlyne.com/equity/share-holding/${pk}/${encodeURIComponent(sym)}/latest/x/`);
      if (shHtml) { try { parseHold(pk, shHtml); } catch (e) { errs++; } } else errs++;
      done++;
      if (done % 20 === 0 || done === stocks.length) {
        const rate = done / ((Date.now() - t0) / 1000);
        const eta = Math.round((stocks.length - done) / Math.max(rate, 0.01) / 60);
        log(`stocks ${done}/${stocks.length} · rows ${(totalRows/1e3).toFixed(0)}k · noSym ${noSym} · errs ${errs} · ETA ~${eta}m`);
      }
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  for (const t in HEADERS) flush(t);
  download('tl_sector_map.csv', sectorRows.join('\n') + '\n');
  log(`DONE · ${done} stocks · ${(totalRows/1e3).toFixed(0)}k rows · noSym ${noSym} · errs ${errs}`);
  stop.textContent = 'Done ✓'; stop.disabled = true;
})();
