/* ============================================================================
   Trendlyne MEGACAP Harvester — Windfall Labs  (BUGFIX)
   ----------------------------------------------------------------------------
   The screener universe ("Others | Listed on NSE") silently dropped the top ~100
   megacaps (RELIANCE, TCS, HDFCBANK, …). This pulls ALL datasets for those 100
   by symbol->pk directly (bypassing the screener), in ONE run, so every table in
   trendlyne_data/ AND trendlyne_data_v2/ gets the megacaps.

   RUN: logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.
        ~15-25 min (100 stocks × all datasets). Click "Allow" on multi-download.

   OUTPUT (Downloads) — same schemas as the main tables, "_megacap" suffix:
     tl_dvm_history_megacap.csv (pk,score,date,value)
     tl_valuation_ratios / pnl_quarterly / growth_quality / ownership _megacap.csv (pk,metric,date,value)
     tl_pnl_annual / balance_sheet / cashflow / ratios_annual / financials_other _megacap.csv (pk,metric,date,value)
     tl_corporate_actions_megacap.csv (pk,action_type,ex_date,record_date,value,detail)
     tl_result_dates_megacap.csv (pk,date,purpose) · tl_shareholding_summary_megacap.csv (pk,category,date,pct)
     tl_sector_map_megacap.csv (pk,sector,industry) · tl_ohlcv_megacap.csv (pk,date,open,high,low,close,last,volume)
     tl_megacap_stocks.csv (pk,nsecode,name,d_now,v_now,m_now)  ← APPEND to _reference/tl_stocks.csv
   Merge each into the matching folder (as the next partNN).
============================================================================ */
(async () => {
  const SYMBOLS = "ABB,ADANIENSOL,ADANIENT,ADANIGREEN,ADANIPORTS,ADANIPOWER,APOLLOHOSP,ASIANPAINT,AXISBANK,BAJAJ-AUTO,BAJAJFINSV,BAJAJHLDNG,BAJFINANCE,BANKBARODA,BEL,BHARTIARTL,BHEL,BOSCHLTD,BPCL,BRITANNIA,BSE,CANBK,CGPOWER,CHOLAFIN,COALINDIA,CUMMINSIND,DIVISLAB,DLF,DMART,EICHERMOT,ENRIN,ETERNAL,GAIL,GMRAIRPORT,GROWW,GRASIM,GVT&D,HAL,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HINDALCO,HINDUNILVR,HINDZINC,HYUNDAI,ICICIAMC,ICICIBANK,IDEA,INDIANB,INDIGO,INFY,IOC,IRFC,ITC,JINDALSTEL,JIOFIN,JSWSTEEL,KOTAKBANK,LGEINDIA,LICI,LT,LTM,M&M,MARUTI,MOTHERSON,MUTHOOTFIN,NESTLEIND,NTPC,ONGC,PFC,PIDILITIND,PNB,POLYCAB,POWERGRID,POWERINDIA,RELIANCE,SBILIFE,SBIN,SHRIRAMFIN,SIEMENS,SOLARINDS,SUNPHARMA,TATACAP,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,TMCV,TMPV,TORNTPHARM,TRENT,TVSMOTOR,ULTRACEMCO,UNIONBANK,VAML,VBL,VEDL,WIPRO".split(",");
  const CONC = 4;

  const DVM = { TL_DURABILITY_METRIC:'d', TL_VALUATION_METRIC:'v', abs_score:'m' };
  const dvmMiss = [];   // (pk,code) whose history fetch failed - swept before writing (2026-09-07)
  const METRIC_TABLES = {
    valuation_ratios: ['PE_TTM','PEG_TTM','PBV_A'],
    pnl_quarterly: ['TOTAL_SR_Q','SR_Q','OperatingIncome_Q','OI_Q','OP_Q','OPMPCT_Q','DEP_Q','INT_Q','PBT_Q','TAX_Q','NP_Q','EPS_adj_Q','NP_TTM','EPS_TTM'],
    growth_quality: ['REV4Q_Q','SR_TTM_GROWTH','NP_Q_GROWTH','NP_TTM_GROWTH','PITROSKI_F'],
    ownership: ['FIIHOLD','MFHOLD','INSTIHOLD'],
  };
  const TABLE_OF_CAT1 = { 'Income Statement':'pnl_annual','Balance Sheet':'balance_sheet','Cash Flow':'cashflow','Financial Ratios':'ratios_annual' };
  const OTHER = 'financials_other';

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const M = { Jan:'01',Feb:'02',Mar:'03',Apr:'04',May:'05',Jun:'06',Jul:'07',Aug:'08',Sep:'09',Oct:'10',Nov:'11',Dec:'12' };
  const MN = { Jan:0,Feb:1,Mar:2,Apr:3,May:4,Jun:5,Jul:6,Aug:7,Sep:8,Oct:9,Nov:10,Dec:11 };
  const IST = 19800000, dstr = ms => new Date(ms + IST).toISOString().slice(0,10);
  const pDate = l => { const m = String(l).match(/^([A-Za-z]{3})\s+(\d{4})$/); if (!m||!M[m[1]]) return null; const last = new Date(Date.UTC(+m[2], MN[m[1]]+1, 0)).getUTCDate(); return `${m[2]}-${M[m[1]]}-${last}`; };
  const dDMY = s => { const m = (s||'').match(/(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})/); return m ? `${m[3]}-${M[m[2]]}-${String(m[1]).padStart(2,'0')}` : ''; };
  const dPer = s => { let m = s.match(/^([A-Za-z]{3})\s+(\d{4})$/); if (m) { const last = new Date(Date.UTC(+m[2], MN[m[1]]+1, 0)).getUTCDate(); return `${m[2]}-${M[m[1]]}-${last}`; } m = s.match(/^([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})$/); if (m) return `${m[3]}-${M[m[1]]}-${String(m[2]).padStart(2,'0')}`; return ''; };
  const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';
  const cells = tr => [...tr.children].map(c => (c.textContent || '').trim().replace(/\s+/g, ' '));

  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:360px;padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Megacap Harvester</b><div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  let stopped = false;
  const stop = document.createElement('button'); stop.textContent='Stop'; stop.style.cssText='margin-top:8px;padding:4px 10px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer'; stop.onclick=()=>{stopped=true;}; box.appendChild(stop);
  const download = (n,t) => { const u=URL.createObjectURL(new Blob([t],{type:'text/csv'})); const a=document.createElement('a'); a.href=u; a.download=n; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(u),15000); };
  async function getText(u, json) { for (let a=0;a<3;a++){ try { const r=await fetch(u,{credentials:'include',headers:{'X-Requested-With':'XMLHttpRequest'}}); if (r.status===429){await sleep(2500*(a+1));continue;} if (r.status!==200) return null; return json?await r.json():await r.text(); } catch(e){ await sleep(700); } } return null; }

  const B = { dvm_history:['pk,score,date,value'], corporate_actions:['pk,action_type,ex_date,record_date,value,detail'], result_dates:['pk,date,purpose'], shareholding_summary:['pk,category,date,pct'], sector_map:['pk,sector,industry'], ohlcv:['pk,date,open,high,low,close,last,volume'], stocks:['pk,nsecode,name,d_now,v_now,m_now'] };
  for (const t in METRIC_TABLES) B[t] = ['pk,metric,date,value'];
  for (const t of ['pnl_annual','balance_sheet','cashflow','ratios_annual','financials_other']) B[t] = ['pk,metric,date,value'];
  const meta = {};

  async function resolve(sym) { const j = await getText('https://trendlyne.com/equity/api/ac_snames/price/?term='+encodeURIComponent(sym), true); const arr = Array.isArray(j)?j:[]; let m = arr.find(x=>x.category==='Equity'&&((x.value||'').toUpperCase()===sym.toUpperCase()||(x.keyname||'').toUpperCase()===sym.toUpperCase())) || arr.find(x=>x.category==='Equity'); if (!m) return null; const tk = m.ohlc_url && m.ohlc_url.match(/web\/ohlc\/\d+\/([^\/]+)\//); return { pk:m.k, token: tk?tk[1]:null, name:(m.label||'').replace(/\s*-\s*[A-Z0-9&.\-]+$/,'').trim() }; }
  async function hist(pk, code) { const j = await getText(`https://trendlyne.com/equity/all-param-history/${pk}/${encodeURIComponent(code)}/`, true); if (!j) return null; try { return JSON.parse(j.chartData).series[0].data; } catch(e){ return null; } }

  async function proc(sym) {
    const r = await resolve(sym); if (!r || !r.pk) return false;
    const { pk, token, name } = r;
    let dnow='',vnow='',mnow='';
    // DVM
    for (const code in DVM) { const d = await hist(pk, code); if (!(d&&d.length)) dvmMiss.push({ pk, code, sym: String(typeof sym === 'string' ? sym : (sym && sym.sym) || pk) }); if (d&&d.length) { const last=d[d.length-1][1]; if (DVM[code]==='d') dnow=last; if (DVM[code]==='v') vnow=last; if (DVM[code]==='m') mnow=last; for (const [ms,v] of d) B.dvm_history.push(`${pk},${DVM[code]},${dstr(ms)},${v}`); } }
    // metric tables
    for (const tbl in METRIC_TABLES) for (const code of METRIC_TABLES[tbl]) { const d = await hist(pk, code); if (d) for (const [ms,v] of d) B[tbl].push(`${pk},${code},${dstr(ms)},${v}`); }
    // annual dump
    if (token) { const j = await getText(`https://trendlyne.com/fundamentals/get-fundamental_results-v2/${pk}/${token}/`, true); const body = j&&j.body;
      if (body && body.annualDataDump) { const pm = body.parameterMetadata||{}; for (const c in pm){ const md=pm[c]; if (md&&!meta[c]) meta[c]=md; }
        const cons = body.annualDataDump.consolidated; const dA = (cons&&Object.keys(cons).length)?cons:body.annualDataDump.standalone;
        if (dA) for (const per in dA) { const dt=pDate(per); if (!dt) continue; for (const code in dA[per]) { const v=dA[per][code]; if (typeof v!=='number'||!isFinite(v)) continue; const t=TABLE_OF_CAT1[(pm[code]&&pm[code].cat1)]||OTHER; B[t].push(`${pk},${code},${dt},${v}`); } }
      }
    }
    // corp-actions page (+ result dates + sector)
    const caH = await getText(`https://trendlyne.com/equity/corporate-actions/${encodeURIComponent(sym)}/${pk}/x/`);
    if (caH) { const doc = new DOMParser().parseFromString(caH,'text/html');
      for (const t of doc.querySelectorAll('table')) { const H=[...t.querySelectorAll('thead th,thead td')].map(c=>(c.textContent||'').trim()).join('|').toLowerCase(); const trs=[...t.querySelectorAll('tbody tr')];
        if (/bonus ratio/.test(H)) trs.forEach(tr=>{const c=cells(tr);B.corporate_actions.push(`${pk},bonus,${dDMY(c[0])},${dDMY(c[2])},${q(c[1])},${q('')}`);});
        else if (/dividend amount/.test(H)) trs.forEach(tr=>{const c=cells(tr);B.corporate_actions.push(`${pk},dividend,${dDMY(c[0])},${dDMY(c[3])},${q(c[1])},${q((c[2]||'')+'/'+(c[4]||''))}`);});
        else if (/premium/.test(H)) trs.forEach(tr=>{const c=cells(tr);B.corporate_actions.push(`${pk},rights,${dDMY(c[0])},${dDMY(c[4])},${q(c[1])},${q('fv='+(c[2]||'')+';prem='+(c[3]||''))}`);});
        else if (/face value/.test(H)&&/split|old|new/.test(H)) trs.forEach(tr=>{const c=cells(tr);B.corporate_actions.push(`${pk},split,${dDMY(c[0])},,${q(c.slice(1).join(' '))},${q('')}`);});
        else if (/\bpurpose\b/.test(H)) trs.forEach(tr=>{const c=cells(tr);if(dDMY(c[0]))B.result_dates.push(`${pk},${dDMY(c[0])},${q(c[1])}`);});
      }
      const tx=doc.body?doc.body.innerText:''; const s1=tx.match(/SECTOR\s*:\s*([^\n/]+?)\s*(?:INDUSTRY|\/)/i); const s2=tx.match(/INDUSTRY\s*:\s*([^\n]+)/i); B.sector_map.push(`${pk},${q(s1?s1[1].trim():'')},${q(s2?s2[1].trim():'')}`);
    }
    // shareholding page
    const shH = await getText(`https://trendlyne.com/equity/share-holding/${pk}/${encodeURIComponent(sym)}/latest/x/`);
    if (shH) { const doc=new DOMParser().parseFromString(shH,'text/html'); let tbl=null; for (const t of doc.querySelectorAll('table')) if (/summary/i.test((t.querySelector('thead th,thead td')||{}).textContent||'')){tbl=t;break;}
      if (tbl) { const per=[...tbl.querySelectorAll('thead th,thead td')].map(c=>(c.textContent||'').trim().replace(/\s+/g,' ')).slice(1); for (const tr of tbl.querySelectorAll('tbody tr')) { const c=cells(tr); const label=c[0]; if (!label) continue; for (let i=1;i<c.length&&i<=per.length;i++){ const v=c[i].replace(/[%,]/g,''); const d=dPer(per[i-1]); if (d&&v!==''&&v!=='-'&&!isNaN(parseFloat(v))) B.shareholding_summary.push(`${pk},${q(label)},${d},${parseFloat(v)}`); } } }
    }
    // OHLCV
    if (token) { const j = await getText(`https://trendlyne.com/mapp/v1/stock/web/ohlc/${pk}/${token}/`, true); const e=j&&j.body&&j.body.eodData; if (e) for (const row of e){ if (!row||row.length<7) continue; B.ohlcv.push(`${pk},${String(row[0]).slice(0,10)},${row[1]},${row[2]},${row[3]},${row[4]},${row[5]},${row[6]}`); } }
    B.stocks.push(`${pk},${q(sym)},${q(name)},${dnow},${vnow},${mnow}`);
    return true;
  }

  let idx=0, done=0, ok=0; const t0=Date.now();
  async function worker(){ while(!stopped){ const i=idx++; if(i>=SYMBOLS.length) break; try{ if(await proc(SYMBOLS[i])) ok++; }catch(e){} done++; if(done%5===0||done===SYMBOLS.length){ const rate=done/((Date.now()-t0)/1000); const eta=Math.round((SYMBOLS.length-done)/Math.max(rate,0.01)/60); log(`megacaps ${done}/${SYMBOLS.length} (ok ${ok}) · ETA ~${eta}m`); } } }
  await Promise.all(Array.from({length:CONC},worker));

  // ------------------- DVM recovery sweep (added 2026-09-07) ----------------
  // The DVM loop above used to do `if (d && d.length) { push }` with NO else: a
  // failed param was not pushed, not counted, not reported. The stock still wrote
  // its surviving scores and looked fine. Measured 2026-09-07: this run returned
  // d_now on 96/99, v_now on 93/99, m_now on 94/99 - and MOTHERSON reached the
  // ingest carrying only `m`, which would have DELETED its d+v history (the
  // ingest replaces a pk's rows wholesale; its shrink guard caught it).
  // NOTE: this sweep repairs dvm_history only. The d_now/v_now/m_now snapshot
  // columns in tl_stocks_megacap.csv are written inside proc() and may stay blank
  // for a swept name - harmless, the DB keeps its previous snapshot value.
  let dvmStill = [];
  if (dvmMiss.length && !stopped) {
    let sd = 0, sr = 0;
    for (const m of dvmMiss) {
      if (stopped) break;
      let d = null;
      for (let a = 0; a < 4 && !d; a++) { d = await hist(m.pk, m.code); if (!d) await sleep(4000 * (a + 1)); }
      sd++;
      if (d && d.length) { sr++; for (const [ms, v] of d) B.dvm_history.push(`${m.pk},${DVM[m.code]},${dstr(ms)},${v}`); }
      else dvmStill.push(m);
      log(`DVM recovery sweep ${sd}/${dvmMiss.length} · recovered ${sr} · still missing ${dvmStill.length}`);
      await sleep(400);
    }
  }
  if (dvmStill.length) {
    const NL = String.fromCharCode(10);
    download('tl_dvm_misses_megacap.csv', 'pk,sym,score' + NL
      + dvmStill.map(m => `${m.pk},${m.sym},${DVM[m.code]}`).join(NL) + NL);
  }

  for (const t in B) if (B[t].length>1) download(`tl_${t==='dvm_history'?'dvm_history':t}_megacap.csv`, B[t].join('\n')+'\n');
  const md=['code,name,cat1,cat2,unit']; for (const c of Object.keys(meta).sort()) md.push([c,q(meta[c].name),q(meta[c].cat1),q(meta[c].cat2),q(meta[c].unit)].join(',')); download('tl_annual_metadata_megacap.csv', md.join('\n')+'\n');
  log(`DONE · ${ok}/${SYMBOLS.length} megacaps · files downloaded`);
  stop.textContent='Done ✓'; stop.disabled=true;
})();
