(function(){
  if(location.pathname!=='/') return;

  const BLOCK_TARGET_SECONDS=150;
  const DIFF1_HASHES=4294967296;
  const STORAGE_KEY='yerbNetworkHashSamplesV1';
  const RANGES={
    '1H':{hours:1,bucket:60},
    '6H':{hours:6,bucket:300},
    '24H':{hours:24,bucket:600},
    '7D':{hours:168,bucket:3600}
  };
  let selectedRange='24H';
  let busy=false;
  let renderQueued=false;

  function chartTarget(){
    const main=document.querySelector('main#app');
    if(!main) return null;
    const heading=[...main.querySelectorAll('.chart-card h3')]
      .find(h=>h.textContent.trim()==='Share Activity' || h.textContent.trim()==='Network vs Pool Hashrate');
    return heading?.closest('.chart-card')||null;
  }

  function claimCard(){
    const card=chartTarget();
    if(!card) return null;
    const heading=card.querySelector('h3');
    if(heading && heading.textContent.trim()==='Share Activity'){
      card.innerHTML='<h3>Network vs Pool Hashrate</h3><div class="muted small">Loading hashrate data…</div><div class="empty" style="margin-top:12px">Loading chart…</div>';
    }
    return card;
  }

  function readNetworkSamples(){
    try{
      const value=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');
      return Array.isArray(value)?value:[];
    }catch(_){ return []; }
  }

  function recordNetworkSample(hashrate){
    const now=Math.floor(Date.now()/1000);
    let samples=readNetworkSamples().filter(x=>Number(x.ts)>now-(8*86400));
    const last=samples[samples.length-1];
    if(!last || now-Number(last.ts)>=60){
      samples.push({ts:now,hashrate:Number(hashrate||0)});
      if(samples.length>12000) samples=samples.slice(-12000);
      try{ localStorage.setItem(STORAGE_KEY,JSON.stringify(samples)); }catch(_){ }
    }
    return samples;
  }

  function nearestNetwork(samples,ts,fallback){
    if(!samples.length) return fallback;
    let lo=0,hi=samples.length-1;
    while(lo<hi){
      const mid=Math.floor((lo+hi+1)/2);
      if(Number(samples[mid].ts)<=ts) lo=mid; else hi=mid-1;
    }
    const a=samples[lo];
    const b=samples[Math.min(lo+1,samples.length-1)];
    if(!a) return fallback;
    if(!b) return Number(a.hashrate||fallback);
    return Math.abs(Number(a.ts)-ts)<=Math.abs(Number(b.ts)-ts)
      ? Number(a.hashrate||fallback)
      : Number(b.hashrate||fallback);
  }

  function timeLabel(ts,range){
    const d=new Date(ts*1000);
    if(range==='7D') return d.toLocaleDateString([], {month:'short',day:'numeric'});
    return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
  }

  function svgChart(history,networkSamples,networkNow){
    const W=760,H=270,L=64,R=18,T=18,B=36,iw=W-L-R,ih=H-T-B;
    const rows=history.map(x=>({
      ts:Number(x.ts||0),
      pool:Number(x.hashrate||0),
      network:nearestNetwork(networkSamples,Number(x.ts||0),networkNow)
    }));
    const values=[];
    rows.forEach(x=>{values.push(x.pool,x.network);});
    const max=Math.max(...values,1)*1.08;
    const minTs=rows[0]?.ts||0,maxTs=rows[rows.length-1]?.ts||minTs+1;
    const px=ts=>L+((ts-minTs)/Math.max(1,maxTs-minTs))*iw;
    const py=v=>T+ih-Number(v||0)/max*ih;
    const poolPoints=rows.map(x=>`${px(x.ts).toFixed(1)},${py(x.pool).toFixed(1)}`).join(' ');
    const networkPoints=rows.map(x=>`${px(x.ts).toFixed(1)},${py(x.network).toFixed(1)}`).join(' ');
    const poolArea=rows.length?`${L},${T+ih} ${poolPoints} ${W-R},${T+ih}`:'';
    let grid='';
    for(let i=0;i<=4;i++){
      const y=T+ih*i/4,val=max*(1-i/4);
      grid+=`<line class="gridline" x1="${L}" y1="${y}" x2="${W-R}" y2="${y}"/><text class="axis-label" x="4" y="${y+4}">${esc(hashRate(val))}</text>`;
    }
    let xlabels='';
    const count=selectedRange==='7D'?7:5;
    for(let i=0;i<count;i++){
      const ts=minTs+(maxTs-minTs)*(i/Math.max(1,count-1));
      const x=px(ts);
      const anchor=i===0?'start':(i===count-1?'end':'middle');
      xlabels+=`<text class="axis-label" text-anchor="${anchor}" x="${x}" y="${H-8}">${esc(timeLabel(ts,selectedRange))}</text>`;
    }
    const points=rows.map((x,i)=>`<circle class="hover-point" cx="${px(x.ts)}" cy="${py(x.pool)}" r="10" data-index="${i}"/>`).join('');
    return `<div class="network-chart-wrap"><svg class="chart network-pool-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<polygon class="pool-hash-area" points="${poolArea}"/><polyline class="network-hash-line" points="${networkPoints}"/><polyline class="pool-hash-line" points="${poolPoints}"/>${xlabels}${points}<line class="chart-crosshair" x1="0" x2="0" y1="${T}" y2="${T+ih}"/></svg><div class="hash-tooltip" hidden></div></div>`;
  }

  function ensureStyles(){
    if(document.getElementById('network-pool-chart-styles')) return;
    const style=document.createElement('style');
    style.id='network-pool-chart-styles';
    style.textContent=`
      .network-chart-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
      .network-range-buttons{display:flex;gap:5px;flex-wrap:wrap}
      .network-range-buttons button{padding:5px 9px;border-radius:7px;font-size:11px;line-height:1.2}
      .network-range-buttons button.active{border-color:var(--yerb,#65c466);color:#dfffe1;background:rgba(101,196,102,.13)}
      .network-pool-chart{overflow:visible}
      .network-pool-chart .pool-hash-line{fill:none;stroke:var(--yerb,#65c466);stroke-width:2.8;vector-effect:non-scaling-stroke}
      .network-pool-chart .pool-hash-area{fill:rgba(101,196,102,.09)}
      .network-pool-chart .network-hash-line{fill:none;stroke:#74c0fc;stroke-width:2.3;stroke-dasharray:7 5;vector-effect:non-scaling-stroke}
      .network-pool-chart .axis-label{fill:#8fa491;font-size:10px}
      .network-pool-legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;font-size:12px}
      .network-pool-legend .network-dot{background:#74c0fc}
      .network-pool-values{display:flex;gap:20px;flex-wrap:wrap;margin:10px 0 4px;font-size:12px;color:#9caf9d}
      .network-pool-values strong{display:block;color:#e9f7ea;font-size:17px;margin-top:2px}
      .network-chart-wrap{position:relative;margin-top:4px}
      .hover-point{fill:transparent;stroke:transparent;cursor:crosshair}
      .chart-crosshair{stroke:#718477;stroke-width:1;stroke-dasharray:3 3;opacity:0;pointer-events:none;vector-effect:non-scaling-stroke}
      .hash-tooltip{position:absolute;pointer-events:none;z-index:6;padding:8px 10px;border:1px solid #334a38;border-radius:8px;background:rgba(10,18,12,.96);box-shadow:0 8px 24px rgba(0,0,0,.3);font-size:11px;line-height:1.5;white-space:nowrap;color:#dbe8dc;transform:translate(-50%,-110%)}
      .network-sample-note{margin-top:7px;font-size:10px;color:#718477}
    `;
    document.head.appendChild(style);
  }

  function bindChartInteractions(card,rows,networkSamples,networkNow){
    const svg=card.querySelector('.network-pool-chart');
    const tooltip=card.querySelector('.hash-tooltip');
    const crosshair=card.querySelector('.chart-crosshair');
    if(!svg||!tooltip||!crosshair) return;
    const W=760,L=64,R=18;
    const minTs=Number(rows[0]?.ts||0),maxTs=Number(rows[rows.length-1]?.ts||minTs+1);
    function showAt(clientX){
      const rect=svg.getBoundingClientRect();
      const x=Math.max(L,Math.min(W-R,(clientX-rect.left)/rect.width*W));
      const ratio=(x-L)/(W-L-R);
      const ts=minTs+(maxTs-minTs)*ratio;
      let best=rows[0];
      for(const row of rows){ if(Math.abs(Number(row.ts)-ts)<Math.abs(Number(best.ts)-ts)) best=row; }
      if(!best) return;
      const network=nearestNetwork(networkSamples,Number(best.ts),networkNow);
      const pool=Number(best.hashrate||0);
      const share=network>0?pool/network*100:0;
      const sx=L+((Number(best.ts)-minTs)/Math.max(1,maxTs-minTs))*(W-L-R);
      crosshair.setAttribute('x1',sx); crosshair.setAttribute('x2',sx); crosshair.style.opacity='1';
      tooltip.hidden=false;
      tooltip.innerHTML=`<strong>${esc(new Date(Number(best.ts)*1000).toLocaleString())}</strong><br>Pool: ${esc(hashRate(pool))}<br>Network: ${esc(hashRate(network))}<br>Pool share: ${share.toFixed(2)}%`;
      tooltip.style.left=`${(sx/W)*100}%`;
      tooltip.style.top='50%';
    }
    svg.addEventListener('mousemove',e=>showAt(e.clientX));
    svg.addEventListener('mouseleave',()=>{tooltip.hidden=true;crosshair.style.opacity='0';});
    svg.addEventListener('touchmove',e=>{if(e.touches[0]) showAt(e.touches[0].clientX);},{passive:true});
  }

  async function render(){
    const card=claimCard();
    if(!card || busy) return;
    busy=true;
    try{
      const range=RANGES[selectedRange];
      const [history,luck]=await Promise.all([
        get(`/api/pool/history?hours=${range.hours}&bucket=${range.bucket}`).catch(()=>[]),
        get('/api/luck').catch(()=>null)
      ]);
      if(!history.length || !luck) return;
      const difficulty=Number(luck.network_difficulty||0);
      const networkHashrate=difficulty>0 ? difficulty*DIFF1_HASHES/BLOCK_TARGET_SECONDS : 0;
      const poolHashrate=Number(luck.pool_hashrate||0);
      const networkSamples=recordNetworkSample(networkHashrate);
      const cutoff=Math.floor(Date.now()/1000)-range.hours*3600;
      const visibleNetwork=networkSamples.filter(x=>Number(x.ts)>=cutoff);
      const poolShare=networkHashrate>0?poolHashrate/networkHashrate*100:0;
      const currentCard=claimCard();
      if(!currentCard) return;
      ensureStyles();
      currentCard.innerHTML=`
        <div class="network-chart-head"><div><h3>Network vs Pool Hashrate</h3><div class="muted small">Pool estimate compared with Yerbas network hashrate over the selected range.</div></div><div class="network-range-buttons">${Object.keys(RANGES).map(k=>`<button type="button" data-range="${k}" class="${k===selectedRange?'active':''}">${k}</button>`).join('')}</div></div>
        <div class="network-pool-values"><span>Pool now<strong>${hashRate(poolHashrate)}</strong></span><span>Network now<strong>${hashRate(networkHashrate)}</strong></span><span>Pool share<strong>${poolShare.toFixed(2)}%</strong></span></div>
        ${svgChart(history,visibleNetwork,networkHashrate)}
        <div class="network-pool-legend"><span><i class="dot hashdot"></i>Pool hashrate</span><span><i class="dot network-dot"></i>Network hashrate</span></div>
        <div class="network-sample-note">Network history is sampled while this dashboard is viewed; the line becomes historical as samples accumulate. Updated ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}.</div>`;
      currentCard.querySelectorAll('[data-range]').forEach(btn=>btn.addEventListener('click',()=>{selectedRange=btn.dataset.range;render();}));
      bindChartInteractions(currentCard,history,visibleNetwork,networkHashrate);
    }finally{
      busy=false;
    }
  }

  function queueRender(){
    claimCard();
    if(renderQueued) return;
    renderQueued=true;
    requestAnimationFrame(()=>{renderQueued=false;render();});
  }

  function install(){
    ensureStyles();
    queueRender();
    const main=document.querySelector('main#app');
    if(main){
      const observer=new MutationObserver(()=>queueRender());
      observer.observe(main,{childList:true,subtree:true});
    }
    setInterval(render,15000);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
