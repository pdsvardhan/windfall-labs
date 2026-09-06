/* ============================================================================
   Trendlyne RECOVERY Harvester — Windfall Labs
   ----------------------------------------------------------------------------
   Recovers the ~226 stocks that leg-2 AND leg-1.5 skipped because they have a
   BLANK NSE symbol in Trendlyne's screener (many ARE NSE-listed — a data gap).
   Addresses them by pk instead of symbol:
     • token from the equity page  /equity/{pk}/x/x/        (no symbol needed)
     • bulk annual dump            (leg-2 tables)
     • corporate-actions + share-holding pages by pk + dummy symbol (leg-1.5 tables)

   RUN: logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.
        ~10-15 min. Click "Allow" on the multiple-downloads chip.

   OUTPUT (Downloads) — same schemas as the main runs, "_recover" suffix:
     tl_pnl_annual_recover.csv, tl_balance_sheet_recover.csv, tl_cashflow_recover.csv,
     tl_ratios_annual_recover.csv, tl_financials_other_recover.csv   (pk,metric,date,value)
     tl_corporate_actions_recover.csv  (pk,action_type,ex_date,record_date,value,detail)
     tl_result_dates_recover.csv       (pk,date,purpose)
     tl_shareholding_summary_recover.csv (pk,category,date,pct)
     tl_sector_map_recover.csv         (pk,sector,industry)
     tl_recovered_symbols.csv          (pk,nse_symbol)  ← BONUS: patch the blank symbols in tl_stocks.csv
   These get merged into the existing trendlyne_data/<table>/ folders as part02.
============================================================================ */
(async () => {
  const QUERY = 'mcapq > 500';
  const CONC  = 4;
  const TABLE_OF_CAT1 = { 'Income Statement':'pnl_annual','Balance Sheet':'balance_sheet','Cash Flow':'cashflow','Financial Ratios':'ratios_annual' };
  const OTHER = 'financials_other';

  const csrf  = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const M = { Jan:'01',Feb:'02',Mar:'03',Apr:'04',May:'05',Jun:'06',Jul:'07',Aug:'08',Sep:'09',Oct:'10',Nov:'11',Dec:'12' };
  const pDate = l => { const m = String(l).match(/^([A-Za-z]{3})\s+(\d{4})$/); if (!m||!M[m[1]]) return null; const last = new Date(Date.UTC(+m[2], +M[m[1]], 0)).getUTCDate(); return `${m[2]}-${M[m[1]]}-${last}`; };
  const dDMY = s => { const m = (s||'').match(/(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})/); return m ? `${m[3]}-${M[m[2]]}-${String(m[1]).padStart(2,'0')}` : ''; };
  const dPer = s => { let m = s.match(/^([A-Za-z]{3})\s+(\d{4})$/); if (m) { const last = new Date(Date.UTC(+m[2], +M[m[1]], 0)).getUTCDate(); return `${m[2]}-${M[m[1]]}-${last}`; } m = s.match(/^([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})$/); if (m) return `${m[3]}-${M[m[1]]}-${String(m[2]).padStart(2,'0')}`; return ''; };
  const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';
  const cells = tr => [...tr.children].map(c => (c.textContent || '').trim().replace(/\s+/g, ' '));

  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:360px;padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Recovery Harvester</b><div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  let stopped = false;
  const stop = document.createElement('button'); stop.textContent = 'Stop'; stop.style.cssText = 'margin-top:8px;padding:4px 10px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer'; stop.onclick = () => { stopped = true; }; box.appendChild(stop);
  const download = (name, text) => { const url = URL.createObjectURL(new Blob([text], { type:'text/csv' })); const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 15000); };
  async function getHTML(u) { for (let a = 0; a < 3; a++) { try { const r = await fetch(u, { credentials:'include' }); if (r.status === 429) { await sleep(2500*(a+1)); continue; } if (r.status !== 200) return null; return await r.text(); } catch (e) { await sleep(700); } } return null; }

  // 1) stock list -> BLANK-symbol pks only (retry pages)
  log('fetching stock list…');
  const aio = async page => { for (let a = 0; a < 4; a++) { try { const r = await fetch('https://trendlyne.com/fundamentals/api/screener-v2/try-aio/', { method:'POST', credentials:'include', headers:{ 'Content-Type':'application/json','X-CSRFToken':csrf,'X-Requested-With':'XMLHttpRequest' }, body: JSON.stringify({ perPageCount:100, groupType:'all', groupName:'all', sortBy:'mcapq', order:'DESC', query:QUERY, pageNumber:page }) }); if (r.status===429){await sleep(3000*(a+1));continue;} const j = await r.json(); if (j&&j.body&&j.body.tableData) return j.body; } catch(e){} await sleep(1200); } return null; };
  let pks = [], col = {}, seen = new Set();
  for (let p = 1; p <= 80; p++) { const b = await aio(p); if (!b) break; if (p===1) b.tableHeaders.forEach((h,i)=>col[h.unique_name]=i); for (const row of b.tableData) { const pk = row[col.stock_id], sym = (row[col.NSEcode]||'').trim(); if (pk && !sym && !seen.has(pk)) { seen.add(pk); pks.push(pk); } } if (!b.isNextPage) break; await sleep(200); }
  log('blank-symbol stocks to recover: ' + pks.length);

  // output accumulators
  const annual = { pnl_annual:['pk,metric,date,value'], balance_sheet:['pk,metric,date,value'], cashflow:['pk,metric,date,value'], ratios_annual:['pk,metric,date,value'], financials_other:['pk,metric,date,value'] };
  const ca = ['pk,action_type,ex_date,record_date,value,detail'], rd = ['pk,date,purpose'], sh = ['pk,category,date,pct'], sect = ['pk,sector,industry'], syms = ['pk,nse_symbol'];
  const meta = {};

  async function proc(pk) {
    const eq = await getHTML(`https://trendlyne.com/equity/${pk}/x/x/`); if (!eq) return false;
    const tk = eq.match(new RegExp('web/ohlc/' + pk + '/([^/"\\\']+)/')); const token = tk ? tk[1] : null;
    const tt = (eq.match(/<title>([\s\S]*?)<\/title>/)||['',''])[1].replace(/\s+/g,' ');
    const sm = tt.match(/\(([A-Z][A-Z0-9&.\-]{1,14})\)\s+Live/); syms.push(`${pk},${q(sm?sm[1]:'')}`);
    if (token) {
      const r = await fetch(`https://trendlyne.com/fundamentals/get-fundamental_results-v2/${pk}/${token}/`, { credentials:'include', headers:{ 'X-Requested-With':'XMLHttpRequest' } });
      if (r.status === 200) { const b = (await r.json()).body; const pm = b.parameterMetadata || {};
        for (const c in pm) { const md = pm[c]; if (md && !meta[c]) meta[c] = md; }
        const cons = b.annualDataDump && b.annualDataDump.consolidated; const dA = (cons && Object.keys(cons).length) ? cons : (b.annualDataDump && b.annualDataDump.standalone);
        if (dA) for (const per in dA) { const d = pDate(per); if (!d) continue; for (const code in dA[per]) { const v = dA[per][code]; if (typeof v !== 'number' || !isFinite(v)) continue; const t = TABLE_OF_CAT1[(pm[code] && pm[code].cat1)] || OTHER; annual[t].push(`${pk},${code},${d},${v}`); } }
      }
    }
    const caH = await getHTML(`https://trendlyne.com/equity/corporate-actions/x/${pk}/x/`);
    if (caH) { const doc = new DOMParser().parseFromString(caH, 'text/html');
      for (const t of doc.querySelectorAll('table')) { const H = [...t.querySelectorAll('thead th,thead td')].map(c=>(c.textContent||'').trim()).join('|').toLowerCase(); const trs = [...t.querySelectorAll('tbody tr')];
        if (/bonus ratio/.test(H)) trs.forEach(tr=>{const c=cells(tr);ca.push(`${pk},bonus,${dDMY(c[0])},${dDMY(c[2])},${q(c[1])},${q('')}`);});
        else if (/dividend amount/.test(H)) trs.forEach(tr=>{const c=cells(tr);ca.push(`${pk},dividend,${dDMY(c[0])},${dDMY(c[3])},${q(c[1])},${q((c[2]||'')+'/'+(c[4]||''))}`);});
        else if (/premium/.test(H)) trs.forEach(tr=>{const c=cells(tr);ca.push(`${pk},rights,${dDMY(c[0])},${dDMY(c[4])},${q(c[1])},${q('fv='+(c[2]||'')+';prem='+(c[3]||''))}`);});
        else if (/face value/.test(H)&&/split|old|new/.test(H)) trs.forEach(tr=>{const c=cells(tr);ca.push(`${pk},split,${dDMY(c[0])},,${q(c.slice(1).join(' '))},${q('')}`);});
        else if (/\bpurpose\b/.test(H)) trs.forEach(tr=>{const c=cells(tr);if(dDMY(c[0]))rd.push(`${pk},${dDMY(c[0])},${q(c[1])}`);});
      }
      const tx = doc.body ? doc.body.innerText : ''; const s1 = tx.match(/SECTOR\s*:\s*([^\n/]+?)\s*(?:INDUSTRY|\/)/i); const s2 = tx.match(/INDUSTRY\s*:\s*([^\n]+)/i);
      sect.push(`${pk},${q(s1?s1[1].trim():'')},${q(s2?s2[1].trim():'')}`);
    }
    const shH = await getHTML(`https://trendlyne.com/equity/share-holding/${pk}/x/latest/x/`);
    if (shH) { const doc = new DOMParser().parseFromString(shH, 'text/html'); let tbl=null; for (const t of doc.querySelectorAll('table')) if (/summary/i.test((t.querySelector('thead th,thead td')||{}).textContent||'')) { tbl=t; break; }
      if (tbl) { const per = [...tbl.querySelectorAll('thead th,thead td')].map(c=>(c.textContent||'').trim().replace(/\s+/g,' ')).slice(1);
        for (const tr of tbl.querySelectorAll('tbody tr')) { const c = cells(tr); const label = c[0]; if (!label) continue; for (let i=1;i<c.length&&i<=per.length;i++){ const v=c[i].replace(/[%,]/g,''); const d=dPer(per[i-1]); if (d&&v!==''&&v!=='-'&&!isNaN(parseFloat(v))) sh.push(`${pk},${q(label)},${d},${parseFloat(v)}`); } }
      }
    }
    return true;
  }

  let idx = 0, done = 0, ok = 0; const t0 = Date.now();
  async function worker() { while (!stopped) { const i = idx++; if (i >= pks.length) break; try { if (await proc(pks[i])) ok++; } catch (e) {} done++; if (done%10===0||done===pks.length) { const rate=done/((Date.now()-t0)/1000); const eta=Math.round((pks.length-done)/Math.max(rate,0.01)/60); log(`recovered ${done}/${pks.length} (ok ${ok}) · ETA ~${eta}m`); } } }
  await Promise.all(Array.from({ length: CONC }, worker));

  for (const t in annual) if (annual[t].length > 1) download(`tl_${t}_recover.csv`, annual[t].join('\n')+'\n');
  if (ca.length>1)   download('tl_corporate_actions_recover.csv', ca.join('\n')+'\n');
  if (rd.length>1)   download('tl_result_dates_recover.csv', rd.join('\n')+'\n');
  if (sh.length>1)   download('tl_shareholding_summary_recover.csv', sh.join('\n')+'\n');
  if (sect.length>1) download('tl_sector_map_recover.csv', sect.join('\n')+'\n');
  download('tl_recovered_symbols.csv', syms.join('\n')+'\n');
  const md = ['code,name,cat1,cat2,unit']; for (const c of Object.keys(meta).sort()) md.push([c, q(meta[c].name), q(meta[c].cat1), q(meta[c].cat2), q(meta[c].unit)].join(','));
  download('tl_annual_metadata_recover.csv', md.join('\n')+'\n');

  log(`DONE · recovered ${ok}/${pks.length} stocks · files downloaded`);
  stop.textContent = 'Done ✓'; stop.disabled = true;
})();
