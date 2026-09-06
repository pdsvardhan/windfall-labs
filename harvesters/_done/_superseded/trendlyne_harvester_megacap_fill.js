/* ============================================================================
   Trendlyne MEGACAP FILL — Windfall Labs
   ----------------------------------------------------------------------------
   The megacap run produced all tables, but Chrome's "too many downloads" throttle
   blocked the LAST 6 files. This re-pulls ONLY those 6 (ownership + the 5 annual
   statement tables) for the 100 megacaps, and SPACES the downloads so none get blocked.
   (The other 10 megacap files are already good — keep them.)

   RUN: logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.  ~5 min.
        Click "Allow" on the multi-download chip.

   OUTPUT (Downloads), merge into the matching trendlyne_data/<table>/ folders:
     tl_ownership_megacap.csv            (pk,metric,date,value)
     tl_pnl_annual_megacap.csv, tl_balance_sheet_megacap.csv, tl_cashflow_megacap.csv,
     tl_ratios_annual_megacap.csv, tl_financials_other_megacap.csv   (pk,metric,date,value)
     tl_annual_metadata_megacap.csv
============================================================================ */
(async () => {
  const SYMBOLS = "ABB,ADANIENSOL,ADANIENT,ADANIGREEN,ADANIPORTS,ADANIPOWER,APOLLOHOSP,ASIANPAINT,AXISBANK,BAJAJ-AUTO,BAJAJFINSV,BAJAJHLDNG,BAJFINANCE,BANKBARODA,BEL,BHARTIARTL,BHEL,BOSCHLTD,BPCL,BRITANNIA,BSE,CANBK,CGPOWER,CHOLAFIN,COALINDIA,CUMMINSIND,DIVISLAB,DLF,DMART,EICHERMOT,ENRIN,ETERNAL,GAIL,GMRAIRPORT,GROWW,GRASIM,GVT&D,HAL,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HINDALCO,HINDUNILVR,HINDZINC,HYUNDAI,ICICIAMC,ICICIBANK,IDEA,INDIANB,INDIGO,INFY,IOC,IRFC,ITC,JINDALSTEL,JIOFIN,JSWSTEEL,KOTAKBANK,LGEINDIA,LICI,LT,LTM,M&M,MARUTI,MOTHERSON,MUTHOOTFIN,NESTLEIND,NTPC,ONGC,PFC,PIDILITIND,PNB,POLYCAB,POWERGRID,POWERINDIA,RELIANCE,SBILIFE,SBIN,SHRIRAMFIN,SIEMENS,SOLARINDS,SUNPHARMA,TATACAP,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,TMCV,TMPV,TORNTPHARM,TRENT,TVSMOTOR,ULTRACEMCO,UNIONBANK,VAML,VBL,VEDL,WIPRO".split(",");
  const CONC = 4;
  const OWN = ['FIIHOLD','MFHOLD','INSTIHOLD'];
  const TABLE_OF_CAT1 = { 'Income Statement':'pnl_annual','Balance Sheet':'balance_sheet','Cash Flow':'cashflow','Financial Ratios':'ratios_annual' };
  const OTHER = 'financials_other';

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const M = { Jan:'01',Feb:'02',Mar:'03',Apr:'04',May:'05',Jun:'06',Jul:'07',Aug:'08',Sep:'09',Oct:'10',Nov:'11',Dec:'12' };
  const MN = { Jan:0,Feb:1,Mar:2,Apr:3,May:4,Jun:5,Jul:6,Aug:7,Sep:8,Oct:9,Nov:10,Dec:11 };
  const IST = 19800000, dstr = ms => new Date(ms + IST).toISOString().slice(0,10);
  const pDate = l => { const m = String(l).match(/^([A-Za-z]{3})\s+(\d{4})$/); if (!m||M[m[1]]===undefined) return null; const last = new Date(Date.UTC(+m[2], MN[m[1]]+1, 0)).getUTCDate(); return `${m[2]}-${M[m[1]]}-${last}`; };
  const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';

  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:340px;padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Megacap Fill</b><div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  let stopped = false;
  const stop = document.createElement('button'); stop.textContent='Stop'; stop.style.cssText='margin-top:8px;padding:4px 10px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer'; stop.onclick=()=>{stopped=true;}; box.appendChild(stop);
  const download = (n,t) => { const u=URL.createObjectURL(new Blob([t],{type:'text/csv'})); const a=document.createElement('a'); a.href=u; a.download=n; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(u),15000); };
  async function gt(u,j){ for(let a=0;a<3;a++){ try{ const r=await fetch(u,{credentials:'include',headers:{'X-Requested-With':'XMLHttpRequest'}}); if(r.status===429){await sleep(2500*(a+1));continue;} if(r.status!==200) return null; return j?await r.json():await r.text(); }catch(e){ await sleep(700); } } return null; }

  const B = { ownership:['pk,metric,date,value'], pnl_annual:['pk,metric,date,value'], balance_sheet:['pk,metric,date,value'], cashflow:['pk,metric,date,value'], ratios_annual:['pk,metric,date,value'], financials_other:['pk,metric,date,value'] };
  const meta = {};

  async function resolve(sym){ const arr = await gt('https://trendlyne.com/equity/api/ac_snames/price/?term='+encodeURIComponent(sym), 1); const a = Array.isArray(arr)?arr:[]; let m = a.find(x=>x.category==='Equity'&&((x.value||'').toUpperCase()===sym.toUpperCase())) || a.find(x=>x.category==='Equity'); if (!m) return null; const tk = m.ohlc_url && m.ohlc_url.match(/web\/ohlc\/\d+\/([^\/]+)\//); return { pk:m.k, token: tk?tk[1]:null }; }
  async function hist(pk,c){ const j = await gt(`https://trendlyne.com/equity/all-param-history/${pk}/${encodeURIComponent(c)}/`, 1); if (!j) return null; try{ return JSON.parse(j.chartData).series[0].data; }catch(e){ return null; } }

  async function proc(sym){
    const r = await resolve(sym); if (!r || !r.pk) return false; const { pk, token } = r;
    for (const c of OWN){ const d = await hist(pk, c); if (d) for (const [ms,v] of d) B.ownership.push(`${pk},${c},${dstr(ms)},${v}`); }
    if (token){ const j = await gt(`https://trendlyne.com/fundamentals/get-fundamental_results-v2/${pk}/${token}/`, 1); const body = j&&j.body;
      if (body && body.annualDataDump){ const pm = body.parameterMetadata||{}; for (const c in pm){ const md=pm[c]; if (md&&!meta[c]) meta[c]=md; }
        const cons = body.annualDataDump.consolidated; const dA = (cons&&Object.keys(cons).length)?cons:body.annualDataDump.standalone;
        if (dA) for (const per in dA){ const dt=pDate(per); if (!dt) continue; for (const code in dA[per]){ const v=dA[per][code]; if (typeof v!=='number'||!isFinite(v)) continue; const t=TABLE_OF_CAT1[(pm[code]&&pm[code].cat1)]||OTHER; B[t].push(`${pk},${code},${dt},${v}`); } }
      }
    }
    return true;
  }

  let idx=0, done=0, ok=0; const t0=Date.now();
  async function worker(){ while(!stopped){ const i=idx++; if(i>=SYMBOLS.length) break; try{ if(await proc(SYMBOLS[i])) ok++; }catch(e){} done++; if(done%5===0||done===SYMBOLS.length){ const rate=done/((Date.now()-t0)/1000); const eta=Math.round((SYMBOLS.length-done)/Math.max(rate,0.01)/60); log(`fill ${done}/${SYMBOLS.length} (ok ${ok}) · ETA ~${eta}m`); } } }
  await Promise.all(Array.from({length:CONC},worker));

  // SPACED downloads so Chrome doesn't throttle them
  log('downloading (spaced)…');
  for (const t in B){ if (B[t].length>1){ download(`tl_${t}_megacap.csv`, B[t].join('\n')+'\n'); await sleep(1500); } }
  const md=['code,name,cat1,cat2,unit']; for (const c of Object.keys(meta).sort()) md.push([c,q(meta[c].name),q(meta[c].cat1),q(meta[c].cat2),q(meta[c].unit)].join(',')); download('tl_annual_metadata_megacap.csv', md.join('\n')+'\n');
  log(`DONE · ${ok}/${SYMBOLS.length} megacaps · 6 tables + metadata downloaded`);
  stop.textContent='Done ✓'; stop.disabled=true;
})();
