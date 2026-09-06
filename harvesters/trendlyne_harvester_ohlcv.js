/* ============================================================================
   Trendlyne OHLCV Harvester  —  Windfall Labs  (net-new: price history)
   ----------------------------------------------------------------------------
   Daily OHLCV for all ~1,849 stocks + the key indices + India VIX, via the
   mapp endpoint  /mapp/v1/stock/web/ohlc/{pk}/{token}/  ->  body.eodData.

   *** PRICES ARE SPLIT/BONUS-ADJUSTED *** (verified: Reliance Sep-2024 close =
   1471, not the raw ~2950 pre-bonus). Volume is in absolute shares. ~2006→2026.

   RUN: logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.
        ~35-45 min (price payloads are large). Click "Allow" on multi-download.

   OUTPUT (Downloads) — WIDE format (price data is naturally wide):
     tl_ohlcv_partNN.csv     pk,date,open,high,low,close,last,volume   (stocks)
     tl_index_ohlcv.csv      pk,date,open,high,low,close,last,volume   (indices + VIX)
     tl_index_map.csv        pk,name                                    (index reference)
   `pk` joins to _reference/tl_stocks.csv (stocks) / tl_index_map.csv (indices).
   Note: OHLCV is WIDE, not long like the other tables — it's price data; long
   would be ~6x the rows. date = YYYY-MM-DD (IST).
============================================================================ */
(async () => {
  const QUERY = 'mcapq > 500';
  const CONC  = 5;
  const FLUSH_ROWS = 2_000_000;
  const INDICES = { 1887:'Nifty 50', 1893:'Nifty 500', 1888:'Nifty Next 50', 910393:'Nifty Midcap 150', 910398:'Nifty Smallcap 250', 178701:'India VIX' };

  const csrf  = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';

  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:360px;padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · OHLCV Harvester</b><div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  let stopped = false;
  const stop = document.createElement('button'); stop.textContent = 'Stop'; stop.style.cssText = 'margin-top:8px;padding:4px 10px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer'; stop.onclick = () => { stopped = true; }; box.appendChild(stop);
  const download = (name, text) => { const url = URL.createObjectURL(new Blob([text], { type:'text/csv' })); const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 15000); };
  async function getText(u) { for (let a = 0; a < 3; a++) { try { const r = await fetch(u, { credentials:'include', headers:{ 'X-Requested-With':'XMLHttpRequest' } }); if (r.status === 429) { await sleep(2500*(a+1)); continue; } if (r.status !== 200) return null; return await r.text(); } catch (e) { await sleep(700); } } return null; }

  // token: ac_snames by symbol (fast) -> fallback equity page by pk (blank-symbol / indices)
  async function tokBySym(pk, sym) { if (!sym) return null; try { const j = JSON.parse(await getText('https://trendlyne.com/equity/api/ac_snames/price/?term=' + encodeURIComponent(sym))); const m = (Array.isArray(j)?j:[]).find(x => x.k === pk); const mm = m && m.ohlc_url && m.ohlc_url.match(/web\/ohlc\/\d+\/([^\/]+)\//); return mm ? mm[1] : null; } catch (e) { return null; } }
  async function tokByPage(pk) { const h = await getText(`https://trendlyne.com/equity/${pk}/x/x/`); if (!h) return null; const m = h.match(new RegExp('web/ohlc/' + pk + '/([^/"\\\']+)/')); return m ? m[1] : null; }

  function rowsFrom(eodData) { const out = []; for (const r of eodData) { if (!r || r.length < 7) continue; const d = String(r[0]).slice(0,10); out.push(`${d},${r[1]},${r[2]},${r[3]},${r[4]},${r[5]},${r[6]}`); } return out; }
  async function ohlc(pk, token) { const t = await getText(`https://trendlyne.com/mapp/v1/stock/web/ohlc/${pk}/${token}/`); if (!t) return null; try { const e = JSON.parse(t).body.eodData; return e || null; } catch (e) { return null; } }

  // 1) stock list
  log('fetching stock list…');
  const aio = async page => { for (let a=0;a<4;a++){ try { const r = await fetch('https://trendlyne.com/fundamentals/api/screener-v2/try-aio/', { method:'POST', credentials:'include', headers:{ 'Content-Type':'application/json','X-CSRFToken':csrf,'X-Requested-With':'XMLHttpRequest' }, body: JSON.stringify({ perPageCount:100, groupType:'all', groupName:'all', sortBy:'mcapq', order:'DESC', query:QUERY, pageNumber:page }) }); if (r.status===429){await sleep(3000*(a+1));continue;} const j = await r.json(); if (j&&j.body&&j.body.tableData) return j.body; } catch(e){} await sleep(1200); } return null; };
  let stocks = [], col = {}, seen = new Set();
  for (let p=1;p<=80;p++){ const b = await aio(p); if (!b) break; if (p===1) b.tableHeaders.forEach((h,i)=>col[h.unique_name]=i); for (const row of b.tableData){ const pk=row[col.stock_id], sym=(row[col.NSEcode]||'').trim(); if (pk&&!seen.has(pk)){ seen.add(pk); stocks.push({pk,sym}); } } if (!b.isNextPage) break; await sleep(200); }
  if (stocks.length < 1000) { log('⚠ ABORT: only '+stocks.length+' stocks — list truncated, re-run.'); return; }
  log('stocks: ' + stocks.length + ' — pulling OHLCV…');

  // 2) stock OHLCV
  const buf = ['pk,date,open,high,low,close,last,volume']; let part = 1, rows = 0, total = 0;
  const flush = () => { if (!rows) return; download(`tl_ohlcv_part${String(part).padStart(2,'0')}.csv`, buf.join('\n')+'\n'); part++; buf.length=1; rows=0; };
  let idx = 0, done = 0, noTok = 0, errs = 0; const t0 = Date.now();
  async function worker() { while (!stopped) { const i = idx++; if (i >= stocks.length) break; const { pk, sym } = stocks[i];
      let tk = await tokBySym(pk, sym); if (!tk) tk = await tokByPage(pk);
      if (!tk) { noTok++; done++; continue; }
      const e = await ohlc(pk, tk); if (!e) { errs++; done++; continue; }
      for (const line of rowsFrom(e)) { buf.push(`${pk},${line}`); rows++; total++; }
      if (rows >= FLUSH_ROWS) flush();
      done++;
      if (done%25===0||done===stocks.length){ const rate=done/((Date.now()-t0)/1000); const eta=Math.round((stocks.length-done)/Math.max(rate,0.01)/60); log(`stocks ${done}/${stocks.length} · rows ${(total/1e6).toFixed(2)}M · noTok ${noTok} · errs ${errs} · ETA ~${eta}m`); }
  } }
  await Promise.all(Array.from({ length: CONC }, worker));
  flush();

  // 3) indices + VIX
  log('pulling indices + VIX…');
  const ibuf = ['pk,date,open,high,low,close,last,volume']; const imap = ['pk,name'];
  for (const pk of Object.keys(INDICES)) { if (stopped) break; const tk = await tokByPage(+pk); if (!tk) continue; const e = await ohlc(+pk, tk); if (!e) continue; imap.push(`${pk},${q(INDICES[pk])}`); for (const line of rowsFrom(e)) ibuf.push(`${pk},${line}`); await sleep(150); }
  if (ibuf.length>1) download('tl_index_ohlcv.csv', ibuf.join('\n')+'\n');
  download('tl_index_map.csv', imap.join('\n')+'\n');

  log(`DONE · stocks ${done}/${stocks.length} · ${(total/1e6).toFixed(2)}M stock rows · ${part-1} parts · indices ${imap.length-1} · noTok ${noTok} · errs ${errs}`);
  stop.textContent = 'Done ✓'; stop.disabled = true;
})();
