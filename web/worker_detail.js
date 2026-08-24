(function(){
  if(!location.pathname.startsWith('/worker/')) return;

  const workerId=location.pathname.slice('/worker/'.length).replace(/\/$/,'');

  function reasonLabel(value){
    const text=String(value||'Unspecified').trim();
    const labels={
      'duplicate share':'Duplicate share',
      'low difficulty share':'Low difficulty',
      'stale job':'Stale job',
      'job not found':'Stale job',
      'invalid share':'Invalid share',
      'invalid nonce':'Invalid nonce',
      'unauthorized worker':'Unauthorized worker',
      'server error':'Server error',
      'Unspecified':'Unspecified'
    };
    return labels[text]||text.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
  }

  function ensureStyles(){
    if(document.getElementById('yerb-worker-detail-styles')) return;
    const style=document.createElement('style');
    style.id='yerb-worker-detail-styles';
    style.textContent=`
      .worker-detail-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
      .worker-detail-id{margin-top:5px}.worker-detail-grid{grid-template-columns:repeat(3,minmax(150px,1fr))}
      .worker-detail-layout{display:grid;grid-template-columns:minmax(0,2fr) minmax(250px,1fr);gap:18px;align-items:start}
      .worker-reason{margin:0 0 14px}.worker-reason-head{display:flex;justify-content:space-between;gap:12px;margin-bottom:6px}
      .worker-reason-track{height:7px;border-radius:999px;background:#252d27;overflow:hidden}.worker-reason-fill{height:100%;background:#d56b6b}
      .worker-share-result{font-weight:700}.worker-share-result.rejected{color:#ff9a9a}.worker-share-result.accepted{color:#8ee889}
      .worker-detail-layout table td,.worker-detail-layout table th{padding:8px 7px}.worker-blocks{margin-top:18px}
      @media(max-width:850px){.worker-detail-grid{grid-template-columns:repeat(2,minmax(140px,1fr))}.worker-detail-layout{grid-template-columns:1fr}}
      @media(max-width:520px){.worker-detail-grid{grid-template-columns:1fr}.worker-detail-layout table th:nth-child(3),.worker-detail-layout table td:nth-child(3){display:none}}
    `;
    document.head.appendChild(style);
  }

  function rejectionBreakdown(items){
    const rows=Array.isArray(items)?items:[];
    const total=rows.reduce((sum,row)=>sum+Number(row.count||0),0);
    if(!total) return '<div class="empty">No rejected shares recorded.</div>';
    return rows.map(row=>{
      const count=Number(row.count||0),percent=count/total*100;
      return `<div class="worker-reason"><div class="worker-reason-head"><span>${esc(reasonLabel(row.reason))}</span><span>${count.toLocaleString()} · ${percent.toFixed(1)}%</span></div><div class="worker-reason-track"><div class="worker-reason-fill" style="width:${Math.max(1,percent).toFixed(1)}%"></div></div></div>`;
    }).join('');
  }

  function recentShares(items){
    const rows=Array.isArray(items)?items:[];
    if(!rows.length) return '<div class="empty">No shares recorded for this worker.</div>';
    return table(['Time','Result','Difficulty','Reason'],rows.map(row=>`<tr><td>${when(row.ts)}<div class="small muted">${ago(row.ts)}</div></td><td><span class="worker-share-result ${row.accepted?'accepted':'rejected'}">${row.accepted?'Accepted':'Rejected'}</span>${row.block_candidate?'<div class="small ok">Block candidate</div>':''}</td><td>${Number(row.difficulty||0).toFixed(6)}</td><td>${row.accepted?'—':esc(reasonLabel(row.rejection_reason))}</td></tr>`));
  }

  function blocksFound(items){
    const rows=Array.isArray(items)?items:[];
    if(!rows.length) return '<div class="empty">No blocks found by this worker yet.</div>';
    return table(['Height','Status','Confirmations','Found'],rows.map(block=>`<tr><td><a href="${EXPLORER}/block/${encodeURIComponent(block.block_hash||block.height)}" target="_blank" rel="noopener">#${Number(block.height||0).toLocaleString()}</a></td><td>${status(block.status)}</td><td>${Number(block.confirmations||0).toLocaleString()}</td><td>${when(block.submitted_at)}</td></tr>`));
  }

  async function renderWorkerDetail(){
    ensureStyles();
    const x=await get(`/api/worker/${encodeURIComponent(workerId)}/detail?hours=24&bucket=600&share_limit=25`);
    const history=Array.isArray(x.history)?x.history:[];
    const accepted=Number(x.accepted_shares||0),rejected=Number(x.rejected_shares||0),total=accepted+rejected;
    const efficiency=total?accepted/total*100:100;
    const rangeAccepted=Number(x.range_accepted_shares||0),rangeRejected=Number(x.range_rejected_shares||0),rangeTotal=rangeAccepted+rangeRejected;
    const chartData={history,pool_hashrate:Number(x.hashrate||0),network_hashrate:0};
    const chart=history.length?workerChartSvg(history):'<div class="empty">No worker history recorded yet.</div>';

    app.innerHTML=`<a class="back" href="/workers">← Workers</a>
      <section><div class="worker-detail-head"><div><h2 style="margin-bottom:0">${esc(x.name)}</h2><div class="worker-detail-id small muted">Worker #${esc(x.id)} · First seen ${when(x.created_at)} · Last share ${ago(x.last_share_at)}</div><div style="margin-top:7px">${addressLink(x.address)} &nbsp; ${explorerAddress(x.address)}</div></div><div style="text-align:right"><div>${x.active?'<span class="ok">● Active</span>':'<span class="muted">○ Idle</span>'}</div><div class="small muted" style="margin-top:5px">Last seen ${ago(x.last_seen_at)}</div></div></div>
      <div class="grid worker-detail-grid" style="margin-top:18px"><div class="card"><div class="muted">Current Hashrate</div><div class="value">${hashRate(x.hashrate)}</div><div class="small muted">${Number(x.hashrate_window_seconds||120)}-second estimate</div></div><div class="card"><div class="muted">24h Average</div><div class="value">${hashRate(x.average_hashrate)}</div><div class="small muted">Includes idle periods</div></div><div class="card"><div class="muted">Accepted / Rejected</div><div class="value">${accepted.toLocaleString()} / ${rejected.toLocaleString()}</div><div class="small muted">${efficiency.toFixed(2)}% lifetime efficiency</div></div><div class="card"><div class="muted">Last Share Difficulty</div><div class="value">${x.last_share_difficulty==null?'—':Number(x.last_share_difficulty).toFixed(6)}</div><div class="small muted">Most recently submitted share</div></div><div class="card"><div class="muted">24h Shares</div><div class="value">${rangeAccepted.toLocaleString()} / ${rangeRejected.toLocaleString()}</div><div class="small muted">${rangeTotal?(rangeRejected/rangeTotal*100).toFixed(2):'0.00'}% rejected</div></div><div class="card"><div class="muted">Blocks Found</div><div class="value">${Number(x.blocks_found_total||0).toLocaleString()}</div><div class="small muted">Most recent ${Math.min(25,(x.blocks_found||[]).length)} shown below</div></div></div></section>
      <section><div class="section-head"><div><h2 style="margin-bottom:4px">Worker Performance</h2><div class="muted">Hashrate and accepted/rejected shares over the last 24 hours.</div></div></div><div class="chart-card" id="worker-hash-card" style="margin-top:14px">${chart}<div class="hash-legend"><span><i class="hash-dot pool"></i>Worker hashrate</span><span><i class="dot okdot"></i>Accepted shares</span><span><i class="dot baddot"></i>Rejected shares</span></div></div></section>
      <div class="worker-detail-layout"><section><div class="section-head"><div><h2 style="margin-bottom:4px">Recent Shares</h2><div class="muted">Latest work submitted by this worker.</div></div><a href="/shares?address=${encodeURIComponent(x.address)}">All account shares →</a></div>${recentShares(x.recent_shares)}</section><section><div class="section-head"><div><h2 style="margin-bottom:4px">Rejection Reasons</h2><div class="muted">Lifetime rejected shares for this worker.</div></div></div>${rejectionBreakdown(x.rejection_reasons)}</section></div>
      <section class="worker-blocks"><div class="section-head"><div><h2 style="margin-bottom:4px">Blocks Found</h2><div class="muted">Blocks attributed to this worker.</div></div><a href="/blocks">All pool blocks →</a></div>${blocksFound(x.blocks_found)}</section>`;
    if(history.length) bindHashChart(chartData,{cardId:'worker-hash-card',workerId:workerId});
  }

  window.worker=renderWorkerDetail;
  renderWorkerDetail().catch(error=>{app.innerHTML=`<div class="empty bad">${esc(error.message)}</div>`});
})();
