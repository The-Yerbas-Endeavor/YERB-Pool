(function(){
  if(!location.pathname.startsWith('/account/')) return;

  function deriveCurrent(stat){
    if(!stat) return 0;
    const direct=Number(stat.hashrate||stat.combined_hashrate||0);
    if(direct>0) return direct;
    const h=Array.isArray(stat.history)?stat.history:[];
    const tail=h.slice(-2);
    return tail.length?tail.reduce((n,x)=>n+Number(x.hashrate||0),0)/tail.length:0;
  }

  function performanceMarkup(history,current,rangeKey,workerCount){
    const avg=stats(history.map(x=>Number(x.hashrate||0))).avg;
    const accepted=history.reduce((n,x)=>n+Number(x.accepted||0),0);
    const rejected=history.reduce((n,x)=>n+Number(x.rejected||0),0);
    const total=accepted+rejected;
    const efficiency=total>0?accepted/total*100:100;
    const rejectRate=total>0?rejected/total*100:0;
    return `<div class="hash-head"><div><h3>Miner Performance</h3><div class="muted small">Combined hashrate and share activity for every worker on this payout address.</div></div><div class="hash-range">${Object.keys(HASH_RANGES).map(k=>`<button type="button" data-account-range="${k}" class="${k===rangeKey?'active':''}">${k}</button>`).join('')}</div></div>
      <div class="hash-metrics account-hash-metrics">
        <div class="hash-metric"><span>Current hashrate</span><strong>${hashRate(current)}</strong><small>combined active estimate</small></div>
        <div class="hash-metric"><span>${rangeKey} average</span><strong>${hashRate(avg)}</strong><small>combined worker average</small></div>
        <div class="hash-metric"><span>Accepted</span><strong>${accepted.toLocaleString()}</strong><small>shares in selected range</small></div>
        <div class="hash-metric"><span>Rejected</span><strong>${rejected.toLocaleString()}</strong><small>${rejectRate.toFixed(2)}% reject rate</small></div>
        <div class="hash-metric"><span>Efficiency</span><strong>${efficiency.toFixed(2)}%</strong><small>accepted share ratio</small></div>
      </div>
      ${workerChartSvg(history)}
      <div class="hash-legend"><span><i class="hash-dot pool"></i>Miner hashrate</span><span><i class="dot okdot"></i>Accepted shares</span><span><i class="dot baddot"></i>Rejected shares</span></div>
      <div class="hash-footer"><span>Combined activity for ${workerCount} worker${workerCount===1?'':'s'}</span><span>Updated ${new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span></div>`;
  }

  function bindHover(card,history){
    const el=card?.querySelector('.combined-hash-chart');
    const tip=card?.querySelector('.combined-hash-tooltip');
    const cross=card?.querySelector('.hash-crosshair');
    if(!el||!tip||!cross||!history.length) return;
    const W=1120,L=72,R=24,min=Number(history[0].ts||0),max=Number(history[history.length-1].ts||min+1);
    el.onmousemove=e=>{
      const rect=el.getBoundingClientRect();
      const sx=Math.max(L,Math.min(W-R,(e.clientX-rect.left)/rect.width*W));
      const target=min+(max-min)*(sx-L)/(W-L-R);
      let best=history[0];
      for(const x of history) if(Math.abs(Number(x.ts)-target)<Math.abs(Number(best.ts)-target)) best=x;
      const x=L+(Number(best.ts)-min)/Math.max(1,max-min)*(W-L-R);
      cross.setAttribute('x1',x); cross.setAttribute('x2',x); cross.style.opacity='1';
      tip.hidden=false;
      tip.innerHTML=`<strong>${esc(new Date(Number(best.ts)*1000).toLocaleString())}</strong><br><span style="color:#80d985">Miner</span>: ${esc(hashRate(Number(best.hashrate||0)))}<br>Accepted: ${Number(best.accepted||0).toLocaleString()}<br>Rejected: ${Number(best.rejected||0).toLocaleString()}`;
      tip.style.left=`${x/W*100}%`; tip.style.top='58%';
    };
    el.onmouseleave=()=>{tip.hidden=true;cross.style.opacity='0'};
  }

  account=async function(){
    const a=decodeURIComponent(location.pathname.slice('/account/'.length));
    const x=await get('/api/account/'+encodeURIComponent(a));
    const workerIds=(x.workers||[]).map(w=>w.id).filter(v=>v!==undefined&&v!==null);
    let rangeKey='24H';
    let rangeBusy=false;

    async function fetchRange(key){
      const r=HASH_RANGES[key]||HASH_RANGES['24H'];
      const results=await Promise.all(workerIds.map(id=>get(`/api/worker/${encodeURIComponent(id)}/stats?hours=${r.hours}&bucket=${r.bucket}`).catch(()=>null)));
      const good=results.filter(Boolean);
      return {history:aggregateHistory(good),current:good.reduce((n,s)=>n+deriveCurrent(s),0)};
    }

    const initial=await fetchRange(rangeKey);
    app.innerHTML=`<a class="back" href="/miners">← Miners</a><section><h2>Miner Account</h2><div>${addressLink(x.address)} &nbsp; ${explorerAddress(x.address)}</div><div class="grid" style="margin-top:18px"><div class="card"><div class="muted">Mature Balance</div><div class="value">${coin(x.balance_atomic)}</div><div>YERB</div></div><div class="card"><div class="muted">Immature Balance</div><div class="value">${coin(x.immature_balance_atomic)}</div><div>YERB</div></div><div class="card"><div class="muted">Total Earned</div><div class="value">${coin(x.total_earned_atomic)}</div><div>YERB</div></div><div class="card"><div class="muted">Total Paid</div><div class="value">${coin(x.total_paid_atomic)}</div><div>YERB</div></div></div></section><section><div class="chart-grid" style="grid-template-columns:1fr"><div class="chart-card" id="account-hash-card">${initial.history.length?performanceMarkup(initial.history,initial.current,rangeKey,workerIds.length):'<div class="empty">No worker history recorded yet.</div>'}</div></div></section><section><h2>Workers</h2>${x.workers.length?table(['Worker','Accepted','Rejected','Last Seen'],x.workers.map(w=>`<tr><td><a href="/worker/${w.id}"><code>${esc(w.name)}</code></a></td><td>${w.accepted_shares}</td><td>${w.rejected_shares}</td><td>${ago(w.last_seen_at)}</td></tr>`)):'<div class="empty">No workers.</div>'}</section><section><h2>Ledger</h2>${x.ledger.length?table(['Time','Type','Amount','Block','Note'],x.ledger.map(l=>`<tr><td>${when(l.ts)}</td><td>${status(l.entry_type)}</td><td>${coin(l.amount_atomic)} YERB</td><td>${l.block_id??'—'}</td><td>${esc(l.note||'')}</td></tr>`)):'<div class="empty">No ledger entries.</div>'}</section><section><h2>Payout History</h2>${x.payouts.length?table(['ID','Status','Amount','Sent','TXID'],x.payouts.map(p=>`<tr><td>#${p.id}</td><td>${status(p.status)}</td><td>${coin(p.amount_atomic)} YERB</td><td>${when(p.sent_at)}</td><td>${explorerTx(p.txid)}</td></tr>`)):'<div class="empty">No payouts.</div>'}</section>`;

    const style=document.createElement('style');
    style.textContent='#account-hash-card .account-hash-metrics{grid-template-columns:repeat(5,minmax(130px,1fr))}#account-hash-card{min-height:520px}@media(max-width:1000px){#account-hash-card .account-hash-metrics{grid-template-columns:repeat(2,minmax(130px,1fr))}}@media(max-width:520px){#account-hash-card .account-hash-metrics{grid-template-columns:1fr}}';
    document.head.appendChild(style);

    async function bindRangeButtons(history){
      const card=document.getElementById('account-hash-card');
      bindHover(card,history);
      card?.querySelectorAll('[data-account-range]').forEach(btn=>{
        btn.onclick=async()=>{
          const key=btn.dataset.accountRange;
          if(rangeBusy||!HASH_RANGES[key]||key===rangeKey) return;
          rangeBusy=true;
          try{
            rangeKey=key;
            card.innerHTML='<div class="empty">Loading miner performance…</div>';
            const data=await fetchRange(key);
            card.innerHTML=data.history.length?performanceMarkup(data.history,data.current,key,workerIds.length):'<div class="empty">No worker history recorded for this range.</div>';
            await bindRangeButtons(data.history);
          } finally { rangeBusy=false; }
        };
      });
    }
    await bindRangeButtons(initial.history);
  };
})();
