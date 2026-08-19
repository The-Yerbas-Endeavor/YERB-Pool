(function(){
  if(!location.pathname.startsWith('/account/')) return;

  const address=decodeURIComponent(location.pathname.slice('/account/'.length));
  if(!address) return;

  let accountInfo=null;
  let workerIds=[];
  let busy=false;
  let lastShareAt=0;
  let lastShareTimer=null;

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

  function accountMetrics(history,current){
    const avg=stats(history.map(x=>Number(x.hashrate||0))).avg;
    const accepted=history.reduce((n,x)=>n+Number(x.accepted||0),0);
    const rejected=history.reduce((n,x)=>n+Number(x.rejected||0),0);
    const total=accepted+rejected;
    const efficiency=total>0?accepted/total*100:100;
    const rejectRate=total>0?rejected/total*100:0;
    return {avg,accepted,rejected,efficiency,rejectRate,current};
  }

  function accountPerformanceCard(history,current){
    const m=accountMetrics(history,current);
    return `<div class="hash-head"><div><h3>Miner Performance</h3><div class="muted small">Combined hashrate and share activity for every worker on this payout address.</div></div><div class="hash-range">${Object.keys(HASH_RANGES).map(k=>`<button type="button" data-account-range="${k}" class="${k===selectedHashRange?'active':''}">${k}</button>`).join('')}</div></div>
      <div class="hash-metrics account-hash-metrics">
        <div class="hash-metric"><span>Current hashrate</span><strong>${hashRate(m.current)}</strong><small>combined active estimate</small></div>
        <div class="hash-metric"><span>${selectedHashRange} average</span><strong>${hashRate(m.avg)}</strong><small>combined worker average</small></div>
        <div class="hash-metric"><span>Accepted / Rejected</span><strong>${m.accepted.toLocaleString()} / ${m.rejected.toLocaleString()}</strong><small>${m.efficiency.toFixed(2)}% accepted · ${m.rejectRate.toFixed(2)}% rejected</small></div>
        <div class="hash-metric" id="account-last-share-card"><span>Last share submitted</span><strong id="account-last-share-value">${formatSince(lastShareAt)}</strong><small id="account-last-share-time">${lastShareAt?new Date(lastShareAt*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'no submitted share recorded'}</small></div>
        <div class="hash-metric"><span>Efficiency</span><strong>${m.efficiency.toFixed(2)}%</strong><small>accepted share ratio</small></div>
      </div>
      ${workerChartSvg(history)}
      <div class="hash-legend"><span><i class="hash-dot pool"></i>Miner hashrate</span><span><i class="dot okdot"></i>Accepted shares</span><span><i class="dot baddot"></i>Rejected shares</span></div>
      <div class="hash-footer"><span>Combined activity for ${workerIds.length} worker${workerIds.length===1?'':'s'}</span><span>Updated ${new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span></div>`;
  }

  function updateLastShareTimer(){
    const value=document.getElementById('account-last-share-value');
    const detail=document.getElementById('account-last-share-time');
    if(value) value.textContent=formatSince(lastShareAt);
    if(detail) detail.textContent=lastShareAt?new Date(lastShareAt*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'no submitted share recorded';
  }

  function bindHover(history){
    const card=document.getElementById('account-hash-card');
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
      cross.setAttribute('x1',x);cross.setAttribute('x2',x);cross.style.opacity='1';
      tip.hidden=false;
      tip.innerHTML=`<strong>${esc(new Date(Number(best.ts)*1000).toLocaleString())}</strong><br><span style="color:#80d985">Miner</span>: ${esc(hashRate(Number(best.hashrate||0)))}<br>Accepted: ${Number(best.accepted||0).toLocaleString()}<br>Rejected: ${Number(best.rejected||0).toLocaleString()}`;
      tip.style.left=`${x/W*100}%`;tip.style.top='58%';
    };
    el.onmouseleave=()=>{tip.hidden=true;cross.style.opacity='0'};
  }

  function bindRanges(){
    document.querySelectorAll('[data-account-range]').forEach(btn=>{
      btn.onclick=()=>renderRange(btn.dataset.accountRange);
    });
  }

  async function renderRange(key){
    if(busy||!HASH_RANGES[key]) return;
    busy=true;
    try{
      selectedHashRange=key;
      const r=HASH_RANGES[key];
      const results=await Promise.all(workerIds.map(id=>get(`/api/worker/${encodeURIComponent(id)}/stats?hours=${r.hours}&bucket=${r.bucket}`).catch(()=>null)));
      const good=results.filter(Boolean);
      const history=aggregateHistory(good);
      const current=good.reduce((n,s)=>n+deriveCurrent(s),0);
      lastShareAt=Math.max(0,...good.map(s=>Number(s.last_share_at||0)));
      const card=document.getElementById('account-hash-card');
      if(!card) return;
      card.innerHTML=history.length?accountPerformanceCard(history,current):'<div class="empty">No worker history recorded for this range.</div>';
      bindRanges();
      bindHover(history);
      updateLastShareTimer();
    } finally {
      busy=false;
    }
  }

  function cleanTopCards(){
    const accountHeading=[...document.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Miner Account');
    const section=accountHeading?.closest('section');
    const grid=section?.querySelector('.grid');
    if(!grid) return false;
    [...grid.querySelectorAll('.card')].forEach(card=>{
      const label=card.querySelector('.muted')?.textContent?.trim();
      if(label==='Combined Hashrate') card.remove();
    });
    return true;
  }

  function replaceLegacyCharts(){
    const heading=[...document.querySelectorAll('h2')].find(h=>h.textContent.trim().startsWith('Worker Statistics'));
    const section=heading?.closest('section');
    if(!section) return null;
    section.innerHTML='<div class="chart-grid" style="grid-template-columns:1fr"><div class="chart-card" id="account-hash-card"><div class="empty">Loading miner performance…</div></div></div>';
    return document.getElementById('account-hash-card');
  }

  async function waitForAccountDom(maxAttempts=80){
    for(let i=0;i<maxAttempts;i++){
      const heading=[...document.querySelectorAll('h2')].find(h=>h.textContent.trim().startsWith('Worker Statistics'));
      const accountHeading=[...document.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Miner Account');
      if(heading&&accountHeading) return true;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    return false;
  }

  async function init(){
    accountInfo=await get('/api/account/'+encodeURIComponent(address)).catch(()=>null);
    if(!accountInfo) return;
    workerIds=(accountInfo.workers||[]).map(w=>w.id).filter(v=>v!==undefined&&v!==null);

    const ready=await waitForAccountDom();
    if(!ready) return;

    cleanTopCards();
    const card=replaceLegacyCharts();
    if(!card) return;
    await renderRange('24H');
    if(!lastShareTimer) lastShareTimer=setInterval(updateLastShareTimer,1000);
  }

  const style=document.createElement('style');
  style.textContent='#account-hash-card .account-hash-metrics{grid-template-columns:repeat(5,minmax(130px,1fr))}#account-hash-card{min-height:520px}@media(max-width:1000px){#account-hash-card .account-hash-metrics{grid-template-columns:repeat(2,minmax(130px,1fr))}}@media(max-width:520px){#account-hash-card .account-hash-metrics{grid-template-columns:1fr}}';
  document.head.appendChild(style);
  setTimeout(init,0);
})();