(function(){
  if(!location.pathname.startsWith('/account/')) return;

  const WORKER_LINE_COLORS=['#f2c94c','#bb86fc','#ff8a65','#4dd0e1','#f06292'];
  let lastBlockFoundAt=0;
  let lastBlockTimer=null;

  function deriveCurrent(stat){
    if(!stat) return 0;
    const direct=Number(stat.hashrate||stat.combined_hashrate||0);
    if(direct>0) return direct;
    const h=Array.isArray(stat.history)?stat.history:[];
    const tail=h.slice(-2);
    return tail.length?tail.reduce((n,x)=>n+Number(x.hashrate||0),0)/tail.length:0;
  }

  function formatSince(epoch){
    const t=Number(epoch||0);
    if(!t) return 'Never';
    const age=Math.max(0,Math.floor(Date.now()/1000-t));
    if(age<60) return `${age}s ago`;
    if(age<3600){const m=Math.floor(age/60),s=age%60;return `${m}m ${String(s).padStart(2,'0')}s ago`;}
    if(age<86400){const h=Math.floor(age/3600),m=Math.floor((age%3600)/60);return `${h}h ${String(m).padStart(2,'0')}m ago`;}
    const d=Math.floor(age/86400),h=Math.floor((age%86400)/3600);return `${d}d ${h}h ago`;
  }

  function updateLastBlockTimer(){
    const value=document.getElementById('account-last-block-value');
    const detail=document.getElementById('account-last-block-time');
    if(value) value.textContent=formatSince(lastBlockFoundAt);
    if(detail) detail.textContent=lastBlockFoundAt?new Date(lastBlockFoundAt*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'no pool block found by this miner';
  }

  function nearestPoint(history,ts){
    if(!history?.length) return null;
    let best=history[0];
    for(const point of history){
      if(Math.abs(Number(point.ts)-ts)<Math.abs(Number(best.ts)-ts)) best=point;
    }
    return best;
  }

  function accountWorkerChartSvg(history,workerSeries){
    const W=1120,H=340,L=72,R=24,T=22,B=46,iw=W-L-R,ih=H-T-B;
    const rows=Array.isArray(history)?history:[];
    if(!rows.length) return '<div class="empty">No worker history recorded yet.</div>';

    const pmax=Math.max(...rows.map(x=>Number(x.hashrate||0)),1)*1.12;
    const smax=Math.max(...rows.map(x=>Number(x.accepted||0)+Number(x.rejected||0)),1);
    const min=Number(rows[0].ts||0),max=Number(rows[rows.length-1].ts||min+1);
    const px=ts=>L+(Number(ts)-min)/Math.max(1,max-min)*iw;
    const py=v=>T+ih-Number(v||0)/pmax*ih;
    const combinedPts=rows.map(x=>`${px(x.ts).toFixed(1)},${py(x.hashrate).toFixed(1)}`).join(' ');
    const area=`${L},${T+ih} ${combinedPts} ${W-R},${T+ih}`;

    let grid='',bars='',labels='',workerLines='';
    for(let i=0;i<=4;i++){
      const y=T+ih*i/4;
      grid+=`<line class="gridline" x1="${L}" y1="${y}" x2="${W-R}" y2="${y}"/><text class="axis pool-axis" x="4" y="${y+4}">${esc(hashRate(pmax*(1-i/4)))}</text>`;
    }

    const bw=Math.max(2,Math.min(12,iw/Math.max(rows.length,1)*.58)),base=T+ih;
    for(const x of rows){
      const a=Number(x.accepted||0)/smax*ih*.24;
      const r=Number(x.rejected||0)/smax*ih*.24;
      const x0=px(x.ts)-bw/2;
      bars+=`<rect class="share-accepted" x="${x0.toFixed(1)}" y="${(base-a).toFixed(1)}" width="${bw.toFixed(1)}" height="${a.toFixed(1)}"/><rect class="share-rejected" x="${x0.toFixed(1)}" y="${(base-a-r).toFixed(1)}" width="${bw.toFixed(1)}" height="${r.toFixed(1)}"/>`;
    }

    workerSeries.forEach((worker,i)=>{
      const pts=(worker.history||[]).filter(x=>Number(x.ts)>=min&&Number(x.ts)<=max).map(x=>`${px(x.ts).toFixed(1)},${py(x.hashrate).toFixed(1)}`).join(' ');
      if(pts) workerLines+=`<polyline class="account-worker-line" data-worker-series="${i}" points="${pts}" style="stroke:${WORKER_LINE_COLORS[i%WORKER_LINE_COLORS.length]}"/>`;
    });

    const count=selectedHashRange==='7D'?7:6;
    for(let i=0;i<count;i++){
      const ts=min+(max-min)*i/Math.max(1,count-1),x=px(ts),d=new Date(ts*1000);
      const label=selectedHashRange==='7D'?d.toLocaleDateString([],{month:'short',day:'numeric'}):d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
      labels+=`<text class="axis" text-anchor="${i===0?'start':i===count-1?'end':'middle'}" x="${x}" y="${H-10}">${esc(label)}</text>`;
    }

    return `<div class="combined-chart-wrap"><svg class="combined-hash-chart account-worker-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<polygon class="pool-area" points="${area}"/>${bars}<polyline class="pool-line account-combined-line" points="${combinedPts}"/>${workerLines}${labels}<line class="hash-crosshair" x1="0" x2="0" y1="${T}" y2="${T+ih}"/></svg><div class="combined-hash-tooltip" hidden></div></div>`;
  }

  function performanceMarkup(history,current,rangeKey,workerCount,workerSeries){
    const avg=stats(history.map(x=>Number(x.hashrate||0))).avg;
    const accepted=history.reduce((n,x)=>n+Number(x.accepted||0),0);
    const rejected=history.reduce((n,x)=>n+Number(x.rejected||0),0);
    const total=accepted+rejected;
    const efficiency=total>0?accepted/total*100:100;
    const rejectRate=total>0?rejected/total*100:0;
    return `<div class="hash-head"><div><h3>Miner Performance</h3><div class="muted small">Combined hashrate and individual worker performance on this payout address.</div></div><div class="hash-range">${Object.keys(HASH_RANGES).map(k=>`<button type="button" data-account-range="${k}" class="${k===rangeKey?'active':''}">${k}</button>`).join('')}</div></div>
      <div class="hash-metrics account-hash-metrics">
        <div class="hash-metric"><span>Current hashrate</span><strong>${hashRate(current)}</strong><small>combined active estimate</small></div>
        <div class="hash-metric"><span>${rangeKey} average</span><strong>${hashRate(avg)}</strong><small>combined worker average</small></div>
        <div class="hash-metric"><span>Accepted / Rejected</span><strong>${accepted.toLocaleString()} / ${rejected.toLocaleString()}</strong><small>${efficiency.toFixed(2)}% accepted · ${rejectRate.toFixed(2)}% rejected</small></div>
        <div class="hash-metric"><span>Last block found</span><strong id="account-last-block-value">${formatSince(lastBlockFoundAt)}</strong><small id="account-last-block-time">${lastBlockFoundAt?new Date(lastBlockFoundAt*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'no pool block found by this miner'}</small></div>
        <div class="hash-metric"><span>Efficiency</span><strong>${efficiency.toFixed(2)}%</strong><small>accepted share ratio</small></div>
      </div>
      ${accountWorkerChartSvg(history,workerSeries)}
      <div class="hash-legend account-worker-legend"><span><i class="hash-dot pool"></i>Combined</span>${workerSeries.map((w,i)=>`<button type="button" class="worker-series-toggle active" data-worker-toggle="${i}"><i class="worker-series-dot" style="background:${WORKER_LINE_COLORS[i%WORKER_LINE_COLORS.length]}"></i>${esc(w.name)}</button>`).join('')}<span><i class="dot okdot"></i>Accepted shares</span><span><i class="dot baddot"></i>Rejected shares</span></div>
      ${workerCount>workerSeries.length?`<div class="small muted account-worker-note">Showing top ${workerSeries.length} workers by current hashrate.</div>`:''}
      <div class="hash-footer"><span>Combined activity for ${workerCount} worker${workerCount===1?'':'s'}</span><span>Updated ${new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span></div>`;
  }

  function bindHover(card,history,workerSeries){
    const el=card?.querySelector('.combined-hash-chart');
    const tip=card?.querySelector('.combined-hash-tooltip');
    const cross=card?.querySelector('.hash-crosshair');
    if(!el||!tip||!cross||!history.length) return;
    const W=1120,L=72,R=24,min=Number(history[0].ts||0),max=Number(history[history.length-1].ts||min+1);
    el.onmousemove=e=>{
      const rect=el.getBoundingClientRect();
      const sx=Math.max(L,Math.min(W-R,(e.clientX-rect.left)/rect.width*W));
      const target=min+(max-min)*(sx-L)/(W-L-R);
      const best=nearestPoint(history,target);
      const x=L+(Number(best.ts)-min)/Math.max(1,max-min)*(W-L-R);
      cross.setAttribute('x1',x); cross.setAttribute('x2',x); cross.style.opacity='1';
      tip.hidden=false;
      let detail=`<strong>${esc(new Date(Number(best.ts)*1000).toLocaleString())}</strong><br><span style="color:#80d985">Combined</span>: ${esc(hashRate(Number(best.hashrate||0)))}`;
      workerSeries.forEach((worker,i)=>{
        const line=card.querySelector(`[data-worker-series="${i}"]`);
        if(line?.classList.contains('series-hidden')) return;
        const point=nearestPoint(worker.history,Number(best.ts));
        if(point) detail+=`<br><span style="color:${WORKER_LINE_COLORS[i%WORKER_LINE_COLORS.length]}">${esc(worker.name)}</span>: ${esc(hashRate(Number(point.hashrate||0)))}`;
      });
      detail+=`<br>Accepted: ${Number(best.accepted||0).toLocaleString()}<br>Rejected: ${Number(best.rejected||0).toLocaleString()}`;
      tip.innerHTML=detail;
      tip.style.left=`${x/W*100}%`; tip.style.top='58%';
    };
    el.onmouseleave=()=>{tip.hidden=true;cross.style.opacity='0'};
  }

  function bindWorkerToggles(card){
    card?.querySelectorAll('[data-worker-toggle]').forEach(btn=>{
      btn.onclick=()=>{
        const idx=btn.dataset.workerToggle;
        const line=card.querySelector(`[data-worker-series="${idx}"]`);
        if(!line) return;
        const hidden=line.classList.toggle('series-hidden');
        btn.classList.toggle('active',!hidden);
      };
    });
  }

  account=async function(){
    const a=decodeURIComponent(location.pathname.slice('/account/'.length));
    const [x,shareRows]=await Promise.all([
      get('/api/account/'+encodeURIComponent(a)),
      get('/api/shares?address='+encodeURIComponent(a)+'&limit=1000').catch(()=>[])
    ]);
    const foundShares=(Array.isArray(shareRows)?shareRows:[]).filter(s=>Number(s.accepted||0)===1&&Number(s.block_candidate||0)===1);
    lastBlockFoundAt=foundShares.length?Math.max(...foundShares.map(s=>Number(s.ts||0))):0;
    const workers=(x.workers||[]).filter(w=>w.id!==undefined&&w.id!==null);
    let rangeKey='24H';
    let rangeBusy=false;

    async function fetchRange(key){
      const r=HASH_RANGES[key]||HASH_RANGES['24H'];
      const results=await Promise.all(workers.map(async worker=>{
        const stat=await get(`/api/worker/${encodeURIComponent(worker.id)}/stats?hours=${r.hours}&bucket=${r.bucket}`).catch(()=>null);
        return stat?{worker,stat}:null;
      }));
      const good=results.filter(Boolean);
      const workerSeries=good.map(({worker,stat})=>({id:worker.id,name:worker.name||`Worker ${worker.id}`,history:Array.isArray(stat.history)?stat.history:[],current:deriveCurrent(stat)})).sort((a,b)=>b.current-a.current).slice(0,5);
      return {history:aggregateHistory(good.map(x=>x.stat)),current:good.reduce((n,x)=>n+deriveCurrent(x.stat),0),workerSeries};
    }

    const initial=await fetchRange(rangeKey);
    app.innerHTML=`<a class="back" href="/miners">← Miners</a><section><h2>Miner Account</h2><div>${addressLink(x.address)} &nbsp; ${explorerAddress(x.address)}</div><div class="grid" style="margin-top:18px"><div class="card"><div class="muted">Mature Balance</div><div class="value">${coin(x.balance_atomic)}</div><div>YERB</div></div><div class="card"><div class="muted">Immature Balance</div><div class="value">${coin(x.immature_balance_atomic)}</div><div>YERB</div></div><div class="card"><div class="muted">Total Earned</div><div class="value">${coin(x.total_earned_atomic)}</div><div>YERB</div></div><div class="card"><div class="muted">Total Paid</div><div class="value">${coin(x.total_paid_atomic)}</div><div>YERB</div></div></div></section><section><div class="chart-grid" style="grid-template-columns:1fr"><div class="chart-card" id="account-hash-card">${initial.history.length?performanceMarkup(initial.history,initial.current,rangeKey,workers.length,initial.workerSeries):'<div class="empty">No worker history recorded yet.</div>'}</div></div></section><section><h2>Workers</h2>${x.workers.length?table(['Worker','Accepted','Rejected','Last Seen'],x.workers.map(w=>`<tr><td><a href="/worker/${w.id}"><code>${esc(w.name)}</code></a></td><td>${w.accepted_shares}</td><td>${w.rejected_shares}</td><td>${ago(w.last_seen_at)}</td></tr>`)):'<div class="empty">No workers.</div>'}</section><section><h2>Ledger</h2>${x.ledger.length?table(['Time','Type','Amount','Block','Note'],x.ledger.map(l=>`<tr><td>${when(l.ts)}</td><td>${status(l.entry_type)}</td><td>${coin(l.amount_atomic)} YERB</td><td>${l.block_id??'—'}</td><td>${esc(l.note||'')}</td></tr>`)):'<div class="empty">No ledger entries.</div>'}</section><section><h2>Payout History</h2>${x.payouts.length?table(['ID','Status','Amount','Sent','TXID'],x.payouts.map(p=>`<tr><td>#${p.id}</td><td>${status(p.status)}</td><td>${coin(p.amount_atomic)} YERB</td><td>${when(p.sent_at)}</td><td>${explorerTx(p.txid)}</td></tr>`)):'<div class="empty">No payouts.</div>'}</section>`;

    const style=document.createElement('style');
    style.textContent='#account-hash-card .account-hash-metrics{grid-template-columns:repeat(5,minmax(130px,1fr))}#account-hash-card{min-height:520px}.account-worker-chart .account-worker-line{fill:none;stroke-width:1.8;opacity:.92;vector-effect:non-scaling-stroke}.account-worker-chart .account-combined-line{stroke-width:3}.account-worker-chart .share-accepted{fill:rgba(101,196,102,.38)}.account-worker-chart .share-rejected{fill:rgba(255,120,120,.82)}.account-worker-chart .series-hidden{opacity:0}.account-worker-legend{align-items:center}.worker-series-toggle{border:0;background:transparent;color:inherit;padding:2px 5px;cursor:pointer;font:inherit;opacity:.45}.worker-series-toggle.active{opacity:1}.worker-series-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}.account-worker-note{text-align:center;margin-top:5px}@media(max-width:1000px){#account-hash-card .account-hash-metrics{grid-template-columns:repeat(2,minmax(130px,1fr))}}@media(max-width:520px){#account-hash-card .account-hash-metrics{grid-template-columns:1fr}}';
    document.head.appendChild(style);

    async function bindRangeButtons(history,workerSeries){
      const card=document.getElementById('account-hash-card');
      bindHover(card,history,workerSeries);
      bindWorkerToggles(card);
      updateLastBlockTimer();
      card?.querySelectorAll('[data-account-range]').forEach(btn=>{
        btn.onclick=async()=>{
          const key=btn.dataset.accountRange;
          if(rangeBusy||!HASH_RANGES[key]||key===rangeKey) return;
          rangeBusy=true;
          try{
            rangeKey=key;
            card.innerHTML='<div class="empty">Loading miner performance…</div>';
            const data=await fetchRange(key);
            card.innerHTML=data.history.length?performanceMarkup(data.history,data.current,key,workers.length,data.workerSeries):'<div class="empty">No worker history recorded for this range.</div>';
            await bindRangeButtons(data.history,data.workerSeries);
          } finally { rangeBusy=false; }
        };
      });
    }
    await bindRangeButtons(initial.history,initial.workerSeries);
    if(!lastBlockTimer) lastBlockTimer=setInterval(updateLastBlockTimer,1000);
  };
})();
