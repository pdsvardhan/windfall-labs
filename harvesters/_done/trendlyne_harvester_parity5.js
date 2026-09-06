/* ============================================================================
   Trendlyne PARITY-5 Harvester — Windfall Labs
   ----------------------------------------------------------------------------
   Pulls the 13 historically-LIQUID NSE names that are absent from the dataset
   because they sit BELOW the >=Rs500cr harvest floor on Trendlyne's own mcap
   (deliberate floor-lowering, see todo #81 / memory windfall-dvm-history-pull).

   Same all-tables pull as the completeness harvester, SPACED downloads.

   ⚠ GSPL is likely DELISTED (no live Trendlyne page) — ac_snames won't find it,
     so it will report as FAILED. That's expected; GSPL needs the dead-name
     (bhavcopy + screener shares) path instead, handled server-side separately.

   RUN: logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter. ~3 min.
        Click "Allow" if Chrome asks about multiple downloads.

   OUTPUT (Downloads), "_parity5" suffix, merge into matching trendlyne_data folders:
     tl_dvm_history_parity5.csv (pk,score,date,value)
     tl_<valuation_ratios|pnl_quarterly|growth_quality|ownership>_parity5.csv (pk,metric,date,value)
     tl_<pnl_annual|balance_sheet|cashflow|ratios_annual|financials_other>_parity5.csv
     tl_corporate_actions_parity5.csv / tl_result_dates_parity5.csv
     tl_shareholding_summary_parity5.csv / tl_sector_map_parity5.csv
     tl_ohlcv_parity5.csv (pk,date,open,high,low,close,last,volume)
     tl_stocks_parity5.csv (pk,nsecode,name,d_now,v_now,m_now)
============================================================================ */
(async () => {
  const SYMBOLS = ['GSPL','MIRZAINT','UGARSUGAR','SHANKARA','ORIENTBELL','KESORAMIND',
                   '3IINFOLTD','HCL-INSYS','VINYLINDIA','SAKUMA','OMAXAUTO','APCL','RAMAPHO'];
  const CONC = 2;
  const DVM = { TL_DURABILITY_METRIC:'d', TL_VALUATION_METRIC:'v', abs_score:'m' };
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
  const pDate = l => { const m = String(l).match(/^([A-Za-z]{3})\s+(\d{4})$/); if (!m||M[m[1]]===undefined) return null; const last = new Date(Date.UTC(+m[2], MN[m[1]]+1, 0)).getUTCDate(); return `${m[2]}-${M[m[1]]}-${last}`; };
  const dDMY = s => { const m = (s||'').match(/(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})/); return m ? `${m[3]}-${M[m[2]]}-${String(m[1]).padStart(2,'0')}` : ''; };
  const dPer = s => { let m = s.match(/^([A-Za-z]{3})\s+(\d{4})$/); if (m) { const last = new Date(Date.UTC(+m[2], MN[m[1]]+1, 0)).getUTCDate(); return `${m[2]}-${M[m[1]]}-${last}`; } m = s.match(/^([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})$/); if (m) return `${m[3]}-${M[m[1]]}-${String(m[2]).padStart(2,'0')}`; return ''; };
  const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';
  const cells = tr => [...tr.children].map(c => (c.textContent || '').trim().replace(/\s+/g, ' '));

  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:340px;padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · PARITY-5 (13 stocks)</b><div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  const download = (n,t) => { const u=URL.createObjectURL(new Blob([t],{type:'text/csv'})); const a=document.createElement('a'); a.href=u; a.download=n; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(u),15000); };
  async function getText(u, json) { for (let a=0;a<3;a++){ try { const r=await fetch(u,{credentials:'include',headers:{'X-Requested-With':'XMLHttpRequest'}}); if (r.status===429){await sleep(2500*(a+1));continue;} if (r.status!==200) return null; return json?await r.json():await r.text(); } catch(e){ await sleep(700); } } return null; }

  const B = { dvm_history:['pk,score,date,value'], corporate_actions:['pk,action_type,ex_date,record_date,value,detail'], result_dates:['pk,date,purpose'], shareholding_summary:['pk,category,date,pct'], sector_map:['pk,sector,industry'], ohlcv:['pk,date,open,high,low,close,last,volume'], stocks:['pk,nsecode,name,d_now,v_now,m_now'] };
  for (const t in METRIC_TABLES) B[t] = ['pk,metric,date,value'];
  for (const t of ['pnl_annual','balance_sheet','cashflow','ratios_annual','financials_other']) B[t] = ['pk,metric,date,value'];

  const FAILED = [];
  async function resolve(sym){ const j=await getText('https://trendlyne.com/equity/api/ac_snames/price/?term='+encodeURIComponent(sym),true); const arr=Array.isArray(j)?j:[]; let m=arr.find(x=>x.category==='Equity'&&((x.value||'').toUpperCase()===sym.toUpperCase()))||arr.find(x=>x.category==='Equity'); if(!m)return null; const tk=m.ohlc_url&&m.ohlc_url.match(/web\/ohlc\/\d+\/([^\/]+)\//); return {pk:m.k,token:tk?tk[1]:null,name:(m.label||'').replace(/\s*-\s*[A-Z0-9&.\-]+$/,'').trim()}; }
  async function hist(pk,code){ const j=await getText(`https://trendlyne.com/equity/all-param-history/${pk}/${encodeURIComponent(code)}/`,true); if(!j)return null; try{return JSON.parse(j.chartData).series[0].data;}catch(e){return null;} }

  async function proc(sym){
    const r=await resolve(sym); if(!r||!r.pk){FAILED.push(sym);return false;} const {pk,token,name}=r; let dn='',vn='',mn='';
    for(const code in DVM){const d=await hist(pk,code);if(d&&d.length){const lv=d[d.length-1][1];if(DVM[code]==='d')dn=lv;if(DVM[code]==='v')vn=lv;if(DVM[code]==='m')mn=lv;for(const [ms,v] of d)B.dvm_history.push(`${pk},${DVM[code]},${dstr(ms)},${v}`);}}
    for(const tbl in METRIC_TABLES)for(const code of METRIC_TABLES[tbl]){const d=await hist(pk,code);if(d)for(const [ms,v] of d)B[tbl].push(`${pk},${code},${dstr(ms)},${v}`);}
    if(token){const j=await getText(`https://trendlyne.com/fundamentals/get-fundamental_results-v2/${pk}/${token}/`,true);const body=j&&j.body;if(body&&body.annualDataDump){const pm=body.parameterMetadata||{};const cons=body.annualDataDump.consolidated;const dA=(cons&&Object.keys(cons).length)?cons:body.annualDataDump.standalone;if(dA)for(const per in dA){const dt=pDate(per);if(!dt)continue;for(const code in dA[per]){const v=dA[per][code];if(typeof v!=='number'||!isFinite(v))continue;B[TABLE_OF_CAT1[(pm[code]&&pm[code].cat1)]||OTHER].push(`${pk},${code},${dt},${v}`);}}}}
    const caH=await getText(`https://trendlyne.com/equity/corporate-actions/${encodeURIComponent(sym)}/${pk}/x/`);
    if(caH){const doc=new DOMParser().parseFromString(caH,'text/html');for(const t of doc.querySelectorAll('table')){const H=[...t.querySelectorAll('thead th,thead td')].map(c=>(c.textContent||'').trim()).join('|').toLowerCase();const trs=[...t.querySelectorAll('tbody tr')];if(/bonus ratio/.test(H))trs.forEach(tr=>{const c=cells(tr);B.corporate_actions.push(`${pk},bonus,${dDMY(c[0])},${dDMY(c[2])},${q(c[1])},${q('')}`);});else if(/dividend amount/.test(H))trs.forEach(tr=>{const c=cells(tr);B.corporate_actions.push(`${pk},dividend,${dDMY(c[0])},${dDMY(c[3])},${q(c[1])},${q((c[2]||'')+'/'+(c[4]||''))}`);});else if(/premium/.test(H))trs.forEach(tr=>{const c=cells(tr);B.corporate_actions.push(`${pk},rights,${dDMY(c[0])},${dDMY(c[4])},${q(c[1])},${q('fv='+(c[2]||'')+';prem='+(c[3]||''))}`);});else if(/\bpurpose\b/.test(H))trs.forEach(tr=>{const c=cells(tr);if(dDMY(c[0]))B.result_dates.push(`${pk},${dDMY(c[0])},${q(c[1])}`);});}const tx=doc.body?doc.body.innerText:'';const s1=tx.match(/SECTOR\s*:\s*([^\n/]+?)\s*(?:INDUSTRY|\/)/i),s2=tx.match(/INDUSTRY\s*:\s*([^\n]+)/i);B.sector_map.push(`${pk},${q(s1?s1[1].trim():'')},${q(s2?s2[1].trim():'')}`);}
    const shH=await getText(`https://trendlyne.com/equity/share-holding/${pk}/${encodeURIComponent(sym)}/latest/x/`);
    if(shH){const doc=new DOMParser().parseFromString(shH,'text/html');let tbl=null;for(const t of doc.querySelectorAll('table'))if(/summary/i.test((t.querySelector('thead th,thead td')||{}).textContent||'')){tbl=t;break;}if(tbl){const per=[...tbl.querySelectorAll('thead th,thead td')].map(c=>(c.textContent||'').trim().replace(/\s+/g,' ')).slice(1);for(const tr of tbl.querySelectorAll('tbody tr')){const c=cells(tr);if(!c[0])continue;for(let i=1;i<c.length&&i<=per.length;i++){const v=c[i].replace(/[%,]/g,'');const d=dPer(per[i-1]);if(d&&v!==''&&v!=='-'&&!isNaN(parseFloat(v)))B.shareholding_summary.push(`${pk},${q(c[0])},${d},${parseFloat(v)}`);}}}}
    if(token){const j=await getText(`https://trendlyne.com/mapp/v1/stock/web/ohlc/${pk}/${token}/`,true);const e=j&&j.body&&j.body.eodData;if(e)for(const row of e){if(!row||row.length<7)continue;B.ohlcv.push(`${pk},${String(row[0]).slice(0,10)},${row[1]},${row[2]},${row[3]},${row[4]},${row[5]},${row[6]}`);}}
    B.stocks.push(`${pk},${q(sym)},${q(name)},${dn},${vn},${mn}`);
    return true;
  }

  let idx=0, ok=0;
  async function worker(){ while(true){ const i=idx++; if(i>=SYMBOLS.length)break; log('pulling '+SYMBOLS[i]+'… ('+(i+1)+'/'+SYMBOLS.length+')'); try{ if(await proc(SYMBOLS[i]))ok++; }catch(e){FAILED.push(SYMBOLS[i]);} } }
  await Promise.all(Array.from({length:CONC},worker));

  log('downloading (spaced)…');
  for (const t in B){ if (B[t].length>1){ download(`tl_${t}_parity5.csv`, B[t].join('\n')+'\n'); await sleep(1500); } }
  log(`DONE · ${ok}/${SYMBOLS.length} stocks ok · failed: ${FAILED.length?FAILED.join(', '):'none'} · files in Downloads`);
  console.log('PARITY-5 harvest done. ok='+ok+'/'+SYMBOLS.length+' failed=['+FAILED.join(', ')+']');
})();
