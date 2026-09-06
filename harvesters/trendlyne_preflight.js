/* ============================================================================
   Trendlyne PREFLIGHT  —  Windfall Labs
   ----------------------------------------------------------------------------
   RUN THIS FIRST. ~15 seconds. It answers one question: does this logged-in
   session actually return DVM data, or will the 20-minute harvest come back
   empty again?

   WHY IT EXISTS
     2026-09-05: the subscription had lapsed. The megacap run returned real
     prices and fundamentals but EMPTY d_now,v_now,m_now; the DVM harvester
     produced tl_stocks.csv and zero history parts. 30 minutes burned for
     nothing. This checks both of those failure modes up front.

   HOW TO RUN
     1. Open any trendlyne.com page while LOGGED IN.
     2. F12 -> Console -> paste this whole file -> Enter.
     3. Read the verdict. GREEN = start the real harvesters. RED = stop.
============================================================================ */
(async () => {
  const csrf = (document.cookie.match(/(?:^|;)\s*csrftoken\s*=\s*([^;]+)/) || [])[1] || '';
  const line = (s) => console.log('%c' + s, 'font:13px/1.6 monospace');
  const ok   = (s) => console.log('%c PASS %c ' + s, 'background:#16a34a;color:#fff;font-weight:700', 'font:13px monospace');
  const bad  = (s) => console.log('%c FAIL %c ' + s, 'background:#dc2626;color:#fff;font-weight:700', 'font:13px monospace');

  line('Windfall preflight - checking DVM access...');
  let fails = 0;

  // -- 0) are we even logged in? ---------------------------------------------
  if (!csrf) { bad('no csrftoken cookie - you are not logged in to trendlyne.com'); return; }

  // -- 1) screener: does it return stocks, and are d/v/m populated? -----------
  let stocks = [], col = {};
  try {
    const r = await fetch('https://trendlyne.com/fundamentals/api/screener-v2/try-aio/', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ perPageCount: 100, groupType: 'all', groupName: 'all',
                             sortBy: 'mcapq', order: 'DESC', query: 'mcapq > 500', pageNumber: 1 })
    });
    if (r.status !== 200) { bad(`screener endpoint returned HTTP ${r.status} - session not authorised`); return; }
    const b = (await r.json()).body;
    if (!b || !b.tableData) { bad('screener returned no tableData - filter or endpoint changed'); return; }
    b.tableHeaders.forEach((h, i) => col[h.unique_name] = i);
    stocks = b.tableData.map(row => ({
      pk: row[col.stock_id], sym: row[col.NSEcode] || '',
      d: row[col.d_value], v: row[col.v_value], m: row[col.m_value]
    })).filter(s => s.pk);
  } catch (e) { bad('screener fetch threw: ' + e.message); return; }

  ok(`screener page 1 returned ${stocks.length} stocks`);

  const withDVM = stocks.filter(s => s.d != null && s.d !== '' && s.v != null && s.v !== '' && s.m != null && s.m !== '');
  const pct = Math.round(100 * withDVM.length / Math.max(stocks.length, 1));
  if (withDVM.length === 0) {
    bad(`0/${stocks.length} rows carry d/v/m -> THIS IS THE LAPSED-SUBSCRIPTION SIGNATURE (2026-09-05).`);
    line('     Prices and fundamentals will still download. DVM will be empty. Do not run the harvest.');
    fails++;
  } else if (pct < 80) {
    bad(`only ${withDVM.length}/${stocks.length} (${pct}%) rows carry d/v/m - partial access, investigate before harvesting`);
    fails++;
  } else {
    ok(`d/v/m populated on ${withDVM.length}/${stocks.length} rows (${pct}%) - e.g. ${stocks[0].sym} d=${stocks[0].d} v=${stocks[0].v} m=${stocks[0].m}`);
  }

  // -- 2) history endpoint: the thing the harvester actually loops on ---------
  const probe = (withDVM[0] || stocks[0]);
  const PARAMS = [['d', 'TL_DURABILITY_METRIC'], ['v', 'TL_VALUATION_METRIC'], ['m', 'abs_score']];
  for (const [code, param] of PARAMS) {
    try {
      const r = await fetch(`https://trendlyne.com/equity/all-param-history/${probe.pk}/${param}/`,
                            { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (r.status !== 200) { bad(`history[${code}] HTTP ${r.status} for pk ${probe.pk} (${probe.sym}) - history is locked`); fails++; continue; }
      const pts = JSON.parse((await r.json()).chartData).series[0].data;
      if (!pts || pts.length < 100) { bad(`history[${code}] returned only ${pts ? pts.length : 0} points - expected thousands`); fails++; continue; }
      const first = new Date(pts[0][0]).toISOString().slice(0, 10);
      const last  = new Date(pts[pts.length - 1][0]).toISOString().slice(0, 10);
      ok(`history[${code}] ${pts.length} points, ${first} -> ${last}`);
    } catch (e) { bad(`history[${code}] threw: ${e.message}`); fails++; }
  }

  // -- 3) universe size sanity (the >=1,800 rule) ----------------------------
  line('checking universe size (screener pagination)...');
  let total = 0;
  for (let p = 1; p <= 80; p++) {
    const b = (await fetch('https://trendlyne.com/fundamentals/api/screener-v2/try-aio/', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ perPageCount: 100, groupType: 'all', groupName: 'all',
                             sortBy: 'mcapq', order: 'DESC', query: 'mcapq > 500', pageNumber: p })
    }).then(r => r.json())).body;
    if (!b || !b.tableData) break;
    total += b.tableData.length;
    if (!b.isNextPage) break;
    await new Promise(r => setTimeout(r, 100));
  }
  if (total < 1800) { bad(`universe is ${total} stocks - under the ~1,800 floor, the screener list truncated. Re-run, do not ingest.`); fails++; }
  else ok(`universe is ${total} stocks (healthy run reads ~1,899)`);

  line('');
  if (fails === 0) {
    console.log('%c GREEN - go %c run trendlyne_dvm_harvester.js, then trendlyne_harvester_megacap.js',
                'background:#16a34a;color:#fff;font-weight:700;font-size:14px', 'font:14px monospace');
  } else {
    console.log(`%c RED - stop %c ${fails} check(s) failed. Do not start the harvest.`,
                'background:#dc2626;color:#fff;font-weight:700;font-size:14px', 'font:14px monospace');
  }
})();
