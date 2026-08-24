(function(){
  if(!location.pathname.startsWith('/worker/')) return;

  const workerId=location.pathname.slice('/worker/'.length).replace(/\/$/,'');
  const WORKER_RANGES={
    '1H':{hours:1,bucket:60,label:'1 hr',averageLabel:'1h Average'},
    '6H':{hours:6,bucket:300,label:'6 hr',averageLabel:'6h Average'},
    '12H':{hours:12,bucket:300,label:'12 hr',averageLabel:'12h Average'},
    '24H':{hours:24,bucket:600,label:'24 hr',averageLabel:'24h Average'},
    '7D':{hours:168,bucket:3600,label:'7D',averageLabel:'7d Average'}
  };
  let workerRange='24H',workerRangeBusy=false;

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
      .worker-overview{margin-top:0}
      .worker-overview-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-top:14px}
      .worker-overview-grid .hash-metric{display:block;min-width:0;color:#e9f7ea;transition:.15s ease}
      .worker-overview-grid .hash-metric:hover{border-color:#497b55;text-decoration:none;transform:translateY(-1px)}
      .worker-status{text-align:right}
      .worker-detail-id{margin-top:5px}
      .worker-reason{margin:0 0 14px}.worker-reason-head{display:flex;justify-content:space-between;gap:12px;margin-bottom:6px}
      .worker-reason-track{height:7px;border-radius:999px;background:#252d27;overflow:hidden}.worker-reason-fill{height:100%;background:#d56b6b}
      .worker-share-result{font-weight:700}.worker-share-result.rejected{color:#ff9a9a}.worker-share-result.accepted{color:#8ee889}
      @media(max-width:1000px){.worker-overview-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
      @media(max-width:700px){.worker-overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
      @media(max-width:520px){.worker-overview-grid{grid-template-columns:1fr}.worker-status{text-align:left}}
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

  function workerPerformance(history){
    return `${history.length?workerChartSvg(history):'<div class="empty">No worker history recorded for this range.</div>'}<div class="hash-legend"><span><i class="hash-dot pool"></i>Worker hashrate</span><span><i class="dot okdot"></i>Accepted shares</span><span><i class="dot baddot"></i>Rejected shares</span></div>`;
  }

  function averageHashrate(history){
    return history.length?history.reduce((sum,row)=>sum+Number(row.hashrate||0),0)/history.length:0;
  }

  function bindWorkerRanges(){
    document.querySelectorAll('[data-worker-range]').forEach(button=>{
      button.onclick=async()=>{
        const key=button.dataset.workerRange;
        if(workerRangeBusy||!WORKER_RANGES[key]||key===workerRange) return;
        workerRangeBusy=true;
        document.querySelectorAll('[data-worker-range]').forEach(item=>item.disabled=true);
        try{
          const range=WORKER_RANGES[key];
          const next=await get(`/api/worker/${encodeURIComponent(workerId)}/stats?hours=${range.hours}&bucket=${range.bucket}`);
          workerRange=key;
          selectedHashRange=key;
          document.querySelectorAll('[data-worker-range]').forEach(item=>item.classList.toggle('active',item.dataset.workerRange===key));
          const history=Array.isArray(next.history)?next.history:[];
          const averageLabel=document.getElementById('worker-average-label');
          const averageValue=document.getElementById('worker-average-value');
          if(averageLabel) averageLabel.textContent=range.averageLabel;
          if(averageValue) averageValue.textContent=hashRate(averageHashrate(history));
          const card=document.getElementById('worker-hash-card');
          if(card) card.innerHTML=workerPerformance(history);
          const subtitle=document.getElementById('worker-performance-subtitle');
          if(subtitle) subtitle.textContent=`Hashrate and accepted/rejected shares over the last ${range.label}.`;
          if(history.length){
            const data={history,pool_hashrate:Number(next.hashrate||0),network_hashrate:0};
            bindHashChart(data,{cardId:'worker-hash-card',workerId:workerId});
          }
        } finally {
          workerRangeBusy=false;
          document.querySelectorAll('[data-worker-range]').forEach(item=>item.disabled=false);
        }
      };
    });
  }

  async function renderWorkerDetail(){
    ensureStyles();
    const x=await get(`/api/worker/${encodeURIComponent(workerId)}/detail?hours=24&bucket=600&share_limit=25`);
    const history=Array.isArray(x.history)?x.history:[];
    const accepted=Number(x.accepted_shares||0),rejected=Number(x.rejected_shares||0),total=accepted+rejected;
    const efficiency=total?accepted/total*100:100;
    const chartData={history,pool_hashrate:Number(x.hashrate||0),network_hashrate:0};
    selectedHashRange=workerRange;
    const chart=workerPerformance(history);

    app.innerHTML=`<a class="back" href="/workers">← Workers</a>
      <section class="worker-overview"><div class="section-head"><div><h2 style="margin-bottom:0">${esc(x.name)}</h2><div class="worker-detail-id small muted">Worker #${esc(x.id)} · First seen ${when(x.created_at)} · Last share ${ago(x.last_share_at)}</div><div style="margin-top:7px">${addressLink(x.address)} &nbsp; ${explorerAddress(x.address)}</div></div><div class="worker-status"><div>${x.active?'<span class="ok">● Active</span>':'<span class="muted">○ Idle</span>'}</div><div class="small muted" style="margin-top:5px">Last seen ${ago(x.last_seen_at)}</div></div></div>
      <div class="worker-overview-grid"><a class="hash-metric" href="#worker-performance"><span>Current Hashrate</span><strong>${hashRate(x.hashrate)}</strong><small>${Number(x.hashrate_window_seconds||120)}-second estimate</small></a><a class="hash-metric" href="#worker-performance"><span id="worker-average-label">24h Average</span><strong id="worker-average-value">${hashRate(x.average_hashrate)}</strong><small>Includes idle periods</small></a><a class="hash-metric" href="#recent-shares"><span>Accepted / Rejected</span><strong>${accepted.toLocaleString()} / ${rejected.toLocaleString()}</strong><small>${efficiency.toFixed(2)}% lifetime efficiency</small></a><a class="hash-metric" href="#recent-shares"><span>Last Share Difficulty</span><strong>${x.last_share_difficulty==null?'—':Number(x.last_share_difficulty).toFixed(6)}</strong><small>Most recently submitted share</small></a><a class="hash-metric" href="#recent-shares"><span>Last Submitted Share</span><strong>${x.last_share_at?ago(x.last_share_at):'—'}</strong><small>${x.last_share_at?when(x.last_share_at):'No shares submitted'}</small></a><a class="hash-metric" href="#blocks-found"><span>Blocks Found</span><strong>${Number(x.blocks_found_total||0).toLocaleString()}</strong><small>Most recent ${Math.min(25,(x.blocks_found||[]).length)} shown below</small></a></div></section>
      <section id="worker-performance"><div class="section-head"><div><h2 style="margin-bottom:4px">Worker Performance</h2><div class="muted" id="worker-performance-subtitle">Hashrate and accepted/rejected shares over the last 24 hr.</div></div><div class="hash-range">${Object.entries(WORKER_RANGES).map(([key,range])=>`<button type="button" data-worker-range="${key}" class="${key===workerRange?'active':''}">${range.label}</button>`).join('')}</div></div><div class="chart-card" id="worker-hash-card" style="margin-top:14px">${chart}</div></section>
      <section id="recent-shares"><div class="section-head"><div><h2 style="margin-bottom:4px">Recent Shares</h2><div class="muted">Latest work submitted by this worker.</div></div><a href="/shares?address=${encodeURIComponent(x.address)}">All account shares →</a></div>${recentShares(x.recent_shares)}</section>
      <section><div class="section-head"><div><h2 style="margin-bottom:4px">Rejection Reasons</h2><div class="muted">Lifetime rejected shares for this worker.</div></div></div>${rejectionBreakdown(x.rejection_reasons)}</section>
      <section id="blocks-found"><div class="section-head"><div><h2 style="margin-bottom:4px">Blocks Found</h2><div class="muted">Blocks attributed to this worker.</div></div><a href="/blocks">All pool blocks →</a></div>${blocksFound(x.blocks_found)}</section>`;
    bindWorkerRanges();
    if(history.length) bindHashChart(chartData,{cardId:'worker-hash-card',workerId:workerId});
  }

  window.worker=renderWorkerDetail;
  renderWorkerDetail().catch(error=>{app.innerHTML=`<div class="empty bad">${esc(error.message)}</div>`});
})();
