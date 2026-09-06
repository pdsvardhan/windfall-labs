/* ============================================================================
   Trendlyne GAP-FILL — Windfall Labs  (iter-22, 2026-07-16)
   ----------------------------------------------------------------------------
   WHY: the 2026-07-16 refresh left 5 live large-caps with DVM frozen at 06-19.
   Two causes, both found by diffing the harvest against the DB:
     1. The megacap harvester's SYMBOLS list is STALE — it was built for June's
        top-100 and never included CIPLA / ZYDUSLIFE / LUPIN / LODHA. They are
        also excluded from the base screener ("Others | Listed on NSE" drops the
        index megacaps), so they fall in the crack between the two harvesters.
     2. BSE *is* in the megacap list but failed that run (99/100 returned).

   This pulls ONLY those 5, DVM + OHLCV — the two tables the rebalance reads.
   Same endpoints/parsing as trendlyne_harvester_megacap.js, just a short list.

   2026-07-16 run: 4/5 OK (CIPLA/ZYDUSLIFE/LUPIN/LODHA, all DVM to 07-16).
   BSE returned "NO PK" — the ac_snames symbol search does not resolve "BSE" to
   the stock (the term collides with the exchange itself). Its pk is known from
   the DB (52884), so BSE is now addressed BY PK, taking its token from the
   equity page /equity/{pk}/x/x/ the way trendlyne_harvester_recover.js does for
   blank-symbol names. Re-running is safe/idempotent: pk-keyed, full history.

   RUN: logged-in trendlyne.com tab -> F12 -> Console -> paste -> Enter.  ~1-2 min.
        Click "Allow" if prompted for multiple downloads.

   OUTPUT (Downloads) — drop into Downloads/data alongside the rest:
     tl_dvm_history_gapfill.csv   (pk,score,date,value)
     tl_ohlcv_gapfill.csv         (pk,date,open,high,low,close,last,volume)
     tl_stocks_gapfill.csv        (pk,nsecode,name,d_now,v_now,m_now)

   NOTE: if a name reports "NO PK", it did not resolve — tell Claude which one
   rather than assuming it is absent from Trendlyne.

   2026-09-07 RE-AIMED (24 names). The DVM harvest returned 1,901 screener stocks
   but history for only 1,877 — 24 came back with zero rows. MARICO (Rs105,838cr)
   and SBICARD (Rs62,642cr) are large caps that certainly have history, so those
   are retry-exhausted errs, not genuine absences; neither is in the megacap
   SYMBOLS list, so the megacap run does not cover them. The rest are recent/SME
   listings that may legitimately have no DVM yet — a NO PK or empty result on
   those is fine, not a failure. All 24 are addressed BY PK (taken from
   tl_stocks.csv), which also handles the 3 with a blank NSE symbol.
============================================================================ */
(async () => {
  // symbol -> resolve via ac_snames; {sym, pk} -> address directly by pk (search can't find it).
  const SYMBOLS = [{ sym:'ABSMARINE', pk:2258959 }, { sym:'AIMTRON', pk:2300266 }, { sym:'ANANTRAJ', pk:78 }, { sym:'ANAWIL', pk:3604138 }, { sym:'ANONDITA', pk:3227182 }, { sym:'APSISAERO', pk:3449240 }, { sym:'BAGMANE', pk:3497836 }, { sym:'BAHETI', pk:1160011 }, { sym:'CARERATING', pk:240 }, { sym:'CELLECOR', pk:1681352 }, { sym:'CELLO', pk:1767397 }, { sym:'CITIUSINVT', pk:3480687 }, { sym:'COMMITTED', pk:1563602 }, { sym:'DEEDEV', pk:83147 }, { sym:'E2ERAIL', pk:3368591 }, { sym:'EFFWA', pk:2401653 }, { sym:'EMBDL', pk:580 }, { sym:'ESABINDIA', pk:386 }, { sym:'ESDS', pk:758705 }, { sym:'ETL', pk:3167548 }, { sym:'EUREKAFORB', pk:850674 }, { sym:'FEDERALBNK', pk:412 }, { sym:'FLYSBS', pk:3197523 }, { sym:'FOCE', pk:754056 }, { sym:'FRESHARA', pk:2715951 }, { sym:'GGBL', pk:2401651 }, { sym:'GULFOILLUB', pk:518 }, { sym:'HIRECT', pk:562 }, { sym:'IDFCFIRSTB', pk:1786 }, { sym:'IFBIND', pk:592 }, { sym:'INDIGRID', pk:54525 }, { sym:'INFLUX', pk:3139377 }, { sym:'IWARE', pk:3082277 }, { sym:'KODYTECH', pk:1694303 }, { sym:'KWIL', pk:3428495 }, { sym:'MAHSEAMLES', pk:820 }, { sym:'MSTCLTD', pk:138917 }, { sym:'NAMOEWASTE', pk:2597187 }, { sym:'NHPC', pk:938 }, { sym:'NORTHARC', pk:755077 }, { sym:'NTPCGREEN', pk:2789016 }, { sym:'NXT-INFRA', pk:2406604 }, { sym:'ORIANA', pk:1574263 }, { sym:'OSELDEVICE', pk:2632760 }, { sym:'PARIN', pk:110949 }, { sym:'PARTH', pk:3197522 }, { sym:'PATILAUTOM', pk:3136275 }, { sym:'PK140644', pk:140644 }, { sym:'PK1416032', pk:1416032 }, { sym:'PK1478426', pk:1478426 }, { sym:'PK1493810', pk:1493810 }, { sym:'PK2133789', pk:2133789 }, { sym:'PK2799243', pk:2799243 }, { sym:'PK2896032', pk:2896032 }, { sym:'PK2938269', pk:2938269 }, { sym:'PK2985703', pk:2985703 }, { sym:'PK3104418', pk:3104418 }, { sym:'PK3161385', pk:3161385 }, { sym:'PK3192332', pk:3192332 }, { sym:'PK3196098', pk:3196098 }, { sym:'PK3239027', pk:3239027 }, { sym:'PK3247925', pk:3247925 }, { sym:'PK3248611', pk:3248611 }, { sym:'PK3262880', pk:3262880 }, { sym:'PK3267080', pk:3267080 }, { sym:'PK3274326', pk:3274326 }, { sym:'PK3354106', pk:3354106 }, { sym:'PK3457157', pk:3457157 }, { sym:'PK3520088', pk:3520088 }, { sym:'PK3576898', pk:3576898 }, { sym:'PK3596596', pk:3596596 }, { sym:'PK947816', pk:947816 }, { sym:'PRIZOR', pk:2424197 }, { sym:'PROV', pk:1471516 }, { sym:'QLINE', pk:3517656 }, { sym:'RAYMONDLSL', pk:2613901 }, { sym:'REMUS', pk:1462194 }, { sym:'RIIT', pk:3448665 }, { sym:'SAAKSHI', pk:1706792 }, { sym:'SACHEEROME', pk:3127454 }, { sym:'SAFEENTP', pk:3143500 }, { sym:'SAHANA', pk:1482926 }, { sym:'SAHASRA', pk:2666758 }, { sym:'SHREMINVIT', pk:671911 }, { sym:'SHRIAHIMSA', pk:3036052 }, { sym:'TANKUP', pk:3074278 }, { sym:'TANLA', pk:1350 }, { sym:'TARIL', pk:1417 }, { sym:'TEJASCARGO', pk:2983157 }, { sym:'UCOBANK', pk:1439 }, { sym:'UNIHEALTH', pk:1671909 }, { sym:'UTSSAV', pk:2475493 }, { sym:'VAML', pk:3545207 }, { sym:'VIESL', pk:2609234 }, { sym:'VINSYS', pk:1565402 }, { sym:'VINYAS', pk:1715908 }, { sym:'VIVIDEL', pk:3464471 }, { sym:'WHEELS', pk:1520 }];
  const CONC = 1;                       // 62 names, partial-param retries — go slow, 429s are the whole problem

  const DVM = { TL_DURABILITY_METRIC:'d', TL_VALUATION_METRIC:'v', abs_score:'m' };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const IST = 19800000, dstr = ms => new Date(ms + IST).toISOString().slice(0,10);
  const q = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';

  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;width:380px;padding:14px 16px;background:#0f172a;color:#e2e8f0;font:13px/1.5 system-ui;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.45)';
  box.innerHTML = '<b>Windfall · Gap-fill (98 names)</b><div id="wfp" style="margin-top:6px">starting…</div>';
  document.body.appendChild(box);
  const log = m => { const e = document.getElementById('wfp'); if (e) e.innerHTML = m; };
  const download = (n,t) => { const u=URL.createObjectURL(new Blob([t],{type:'text/csv'})); const a=document.createElement('a'); a.href=u; a.download=n; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(u),15000); };
  async function getText(u, json) { for (let a=0;a<3;a++){ try { const r=await fetch(u,{credentials:'include',headers:{'X-Requested-With':'XMLHttpRequest'}}); if (r.status===429){await sleep(2500*(a+1));continue;} if (r.status!==200) return null; return json?await r.json():await r.text(); } catch(e){ await sleep(700); } } return null; }

  const B = { dvm_history:['pk,score,date,value'], ohlcv:['pk,date,open,high,low,close,last,volume'], stocks:['pk,nsecode,name,d_now,v_now,m_now'] };
  const report = [];

  async function resolve(sym) { const j = await getText('https://trendlyne.com/equity/api/ac_snames/price/?term='+encodeURIComponent(sym), true); const arr = Array.isArray(j)?j:[]; let m = arr.find(x=>x.category==='Equity'&&((x.value||'').toUpperCase()===sym.toUpperCase()||(x.keyname||'').toUpperCase()===sym.toUpperCase())) || arr.find(x=>x.category==='Equity'); if (!m) return null; const tk = m.ohlc_url && m.ohlc_url.match(/web\/ohlc\/\d+\/([^\/]+)\//); return { pk:m.k, token: tk?tk[1]:null, name:(m.label||'').replace(/\s*-\s*[A-Z0-9&.\-]+$/,'').trim() }; }

  // By-pk path for names the symbol search can't find (BSE). The equity page carries the same
  // ohlc token in its markup, so no symbol lookup is needed anywhere.
  async function resolveByPk(pk) {
    const h = await getText(`https://trendlyne.com/equity/${pk}/x/x/`);
    if (!h) return null;
    const tk = h.match(new RegExp('web/ohlc/' + pk + '/([^/"\\\']+)/'));
    // The equity page <title> is an SEO blob spanning newlines — e.g. for BSE:
    //   "BSE (BSE) Live\n Share\n Price Today on\n NSE/BSE, Stock Analysis and Price Estimates"
    // Taking it whole put that entire string into stocks.name. The company name is the leading
    // segment before " (<SYMBOL>)"; fall back to empty rather than emit a blob, since the ingest
    // keeps the existing name when the incoming one is unusable.
    let name = '';
    const t = h.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    if (t) {
      const flat = t[1].replace(/\s+/g, ' ').trim();
      const m = flat.match(/^(.+?)\s*\(/);
      name = (m ? m[1] : flat.split(/\s+[-|]\s+/)[0]).trim();
      if (name.length > 80) name = '';
    }
    return { pk, token: tk ? tk[1] : null, name };
  }

  async function hist(pk, code) { const j = await getText(`https://trendlyne.com/equity/all-param-history/${pk}/${encodeURIComponent(code)}/`, true); if (!j) return null; try { return JSON.parse(j.chartData).series[0].data; } catch(e){ return null; } }

  async function proc(entry) {
    const sym = typeof entry === 'string' ? entry : entry.sym;
    const r = typeof entry === 'string' ? await resolve(sym) : await resolveByPk(entry.pk);
    if (!r || !r.pk) { report.push(`${sym}: NO PK (did not resolve)`); return false; }
    const { pk, token, name } = r;
    let dnow='',vnow='',mnow='', dvmRows=0, ohlcRows=0, lastDvm='';
    for (const code in DVM) {
      const d = await hist(pk, code);
      if (d && d.length) { const last=d[d.length-1]; const lv=last[1];
        if (DVM[code]==='d') dnow=lv; if (DVM[code]==='v') vnow=lv; if (DVM[code]==='m') mnow=lv;
        lastDvm = dstr(last[0]);
        for (const [ms,v] of d) { B.dvm_history.push(`${pk},${DVM[code]},${dstr(ms)},${v}`); dvmRows++; }
      }
    }
    if (token) { const j = await getText(`https://trendlyne.com/mapp/v1/stock/web/ohlc/${pk}/${token}/`, true); const e=j&&j.body&&j.body.eodData;
      if (e) for (const row of e){ if (!row||row.length<7) continue; B.ohlcv.push(`${pk},${String(row[0]).slice(0,10)},${row[1]},${row[2]},${row[3]},${row[4]},${row[5]},${row[6]}`); ohlcRows++; }
    }
    B.stocks.push(`${pk},${q(sym)},${q(name)},${dnow},${vnow},${mnow}`);
    report.push(`${sym}: pk=${pk} dvm=${dvmRows} (to ${lastDvm||'?'}) ohlcv=${ohlcRows}`);
    return true;
  }

  let idx=0, done=0, ok=0;
  const nameOf = e => typeof e === 'string' ? e : e.sym;
  async function worker(){ while(true){ const i=idx++; if(i>=SYMBOLS.length) break; try{ if(await proc(SYMBOLS[i])) ok++; }catch(e){ report.push(`${nameOf(SYMBOLS[i])}: ERROR ${e&&e.message}`); } done++; log(`gap-fill ${done}/${SYMBOLS.length} (ok ${ok})`); } }
  await Promise.all(Array.from({length:CONC},worker));

  for (const t in B) if (B[t].length>1) download(`tl_${t}_gapfill.csv`, B[t].join('\n')+'\n');
  log(`<b>DONE · ${ok}/${SYMBOLS.length}</b><div style="margin-top:6px;font:11px/1.45 ui-monospace,monospace">${report.join('<br>')}</div>`);
  console.log('%c[gap-fill] per-symbol result:', 'font-weight:bold', '\n' + report.join('\n'));
})();
