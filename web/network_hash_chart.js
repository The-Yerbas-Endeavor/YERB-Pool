(function(){
  if(location.pathname!=='/') return;

  const BLOCK_TARGET_SECONDS=150;
  const DIFF1_HASHES=4294967296;
  const STORAGE_KEY='yerbNetworkHashSamplesV2';
  const RANGES={
    '1H':{hours:1,bucket:60},
    '6H':{hours:6,bucket:300},
    '12H':{hours:12,bucket:300},
    '24H':{hours:24,bucket:600},
    '7D':{hours:168,bucket:3600}
  };

  let selectedRange='24H';
  let busy=false;
  let pending=false;

  function cards(){return [...document.querySelectorAll('main#app .chart-card')];}
  function findCard(title){return cards().find(c=>c.querySelector('h3')?.textContent.trim()===title)||null;}

  function combinedCard(){
    let pool=findCard('Pool Hashrate')||findCard('Network Hash vs Pool Hash');
    let other=findCard('Network vs Pool Hashrate')||findCard('Share Activity');
    if(!pool && other) pool=other;
    if(!pool) return null;
    const grid=pool.closest('.chart-grid');
    if(grid){grid.style.gridTemplateColumns='1fr';grid.classList.add('combined-hash-grid');}
    if(other && other!==pool) other.remove();
    pool.classList.add('combined-hash-card');
    if(!pool.dataset.hashCombinedClaimed){
      pool.dataset.hashCombinedClaimed='1';
      pool.innerHTML=`<div class="hash-head"><div><h3>Network Hash vs Pool Hash</h3><div class="muted small">Pool and Yerbas network hashrate over the selected time range.</div></div><div class="hash-range">${Object.keys(RANGES).map(k=>`<button type="button" disabled class="${k===selectedRange?'active':''}">${k}</button>`).join('')}</div></div><div class="hash-loading">Loading hashrate history…</div>`;
    }
    return pool;
  }

  function readSamples(){try{const a=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');return Array.isArray(a)?a:[];}catch(_){return [];}}
  function saveNetworkSample(hashrate){
    const now=Math.floor(Date.now()/1000);
    let a=readSamples().filter(x=>Number(x.ts)>now-8*86400);
    const last=a[a.length-1];
    if(!last || now-Number(last.ts)>=60){a.push({ts:now,hashrate:Number(hashrate||0)});if(a.length>12000)a=a.slice(-12000);try{localStorage.setItem(STORAGE_KEY,JSON.stringify(a));}catch(_){}}
    return a;
  }
  function networkAt(samples,ts,fallback){
    if(!samples.length) return fallback;
    let best=samples[0];
    for(const s of samples){if(Math.abs(Number(s.ts)-ts)<Math.abs(Number(best.ts)-ts)) best=s;}
    return Number(best.hashrate||fallback);
  }
  function timeLabel(ts){const d=new Date(ts*1000);if(selectedRange==='7D')return d.toLocaleDateString([], {month:'short',day:'numeric'});return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}
  function calcStats(values){const v=values.filter(Number.isFinite);if(!v.length)return{avg:0,peak:0};return{avg:v.reduce((a,b)=>a+b,0)/v.length,peak:Math.max(...v)};}

  function chart(history,samples,networkNow){
    const W=1120,H=340,L=72,R=78,T=22,B=46,iw=W-L-R,ih=H-T-B;
    const rows=history.map(x=>({ts:Number(x.ts||0),pool:Number(x.hashrate||0),network:networkAt(samples,Number(x.ts||0),networkNow)}));
    const poolMax=Math.max(...rows.map(x=>x.pool),1)*1.12;
    const networkMax=Math.max(...rows.map(x=>x.network),networkNow,1)*1.12;
    const minTs=rows[0]?.ts||0,maxTs=rows[rows.length-1]?.ts||minTs+1;
    const px=ts=>L+(ts-minTs)/Math.max(1,maxTs-minTs)*iw;
    const pyPool=v=>T+ih-(Number(v||0)/poolMax)*ih;
    const pyNet=v=>T+ih-(Number(v||0)/networkMax)*ih;
    const poolPts=rows.map(r=>`${px(r.ts).toFixed(1)},${pyPool(r.pool).toFixed(1)}`).join(' ');
    const netPts=rows.map(r=>`${px(r.ts).toFixed(1)},${pyNet(r.network).toFixed(1)}`).join(' ');
    const poolArea=rows.length?`${L},${T+ih} ${poolPts} ${W-R},${T+ih}`:'';
    const netArea=rows.length?`${L},${T+ih} ${netPts} ${W-R},${T+ih}`:'';
    let grid='';
    for(let i=0;i<=4;i++){
      const y=T+ih*i/4,pv=poolMax*(1-i/4),nv=networkMax*(1-i/4);
      grid+=`<line class="gridline" x1="${L}" y1="${y}" x2="${W-R}" y2="${y}"/><text class="axis pool-axis" x="4" y="${y+4}">${esc(hashRate(pv))}</text><text class="axis net-axis" text-anchor="end" x="${W-4}" y="${y+4}">${esc(hashRate(nv))}</text>`;
    }
    let labels='';
    const count=selectedRange==='7D'?7:6;
    for(let i=0;i<count;i++){
      const ts=minTs+(maxTs-minTs)*(i/Math.max(1,count-1)),x=px(ts),anchor=i===0?'start':(i===count-1?'end':'middle');
      labels+=`<text class="axis time-axis" text-anchor="${anchor}" x="${x}" y="${H-10}">${esc(timeLabel(ts))}</text>`;
    }
    return `<div class="combined-chart-wrap"><svg class="chart combined-hash-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<polygon class="network-area" points="${netArea}"/><polygon class="pool-area" points="${poolArea}"/><polyline class="network-line" points="${netPts}"/><polyline class="pool-line" points="${poolPts}"/>${labels}<line class="hash-crosshair" x1="0" x2="0" y1="${T}" y2="${T+ih}"/></svg><div class="combined-hash-tooltip" hidden></div></div>`;
  }

  function styles(){
    if(document.getElementById('combined-hash-styles')) return;
    const s=document.createElement('style');s.id='combined-hash-styles';s.textContent=`
      .combined-hash-grid{grid-template-columns:1fr!important}.combined-hash-card{width:100%}.hash-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}.hash-range{display:flex;gap:7px;flex-wrap:wrap}.hash-range button{background:#24242c;color:#eee;border:1px solid #666b78;border-radius:7px;padding:6px 11px;font-size:11px;font-weight:700;cursor:pointer}.hash-range button:disabled{cursor:default;opacity:.75}.hash-range button:hover:not(:disabled){border-color:#85b98a}.hash-range button.active{background:rgba(101,196,102,.15);border-color:var(--yerb,#65c466);color:#e2ffe4}.hash-loading{min-height:340px;display:flex;align-items:center;justify-content:center;color:#819284;font-size:13px}.hash-metrics{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:10px;margin:14px 0}.hash-metric{border:1px solid #2d4332;border-radius:9px;padding:11px 13px;background:#141816}.hash-metric span{display:block;color:#9caf9d;font-size:11px}.hash-metric strong{display:block;color:#e9f7ea;font-size:19px;margin-top:3px}.hash-metric small{display:block;color:#829184;font-size:10px;margin-top:3px}.combined-chart-wrap{position:relative;margin-top:8px}.combined-hash-chart{height:340px;cursor:crosshair;overflow:visible}.combined-hash-chart .pool-line{fill:none;stroke:var(--yerb,#65c466);stroke-width:2.6;vector-effect:non-scaling-stroke}.combined-hash-chart .network-line{fill:none;stroke:#45a3ff;stroke-width:2.4;vector-effect:non-scaling-stroke}.combined-hash-chart .pool-area{fill:rgba(101,196,102,.11)}.combined-hash-chart .network-area{fill:rgba(69,163,255,.08)}.combined-hash-chart .axis{font-size:10px;fill:#8ea091}.combined-hash-chart .pool-axis{fill:#80d985}.combined-hash-chart .net-axis{fill:#6eb7ff}.hash-crosshair{stroke:#8b968d;stroke-width:1;stroke-dasharray:4 4;opacity:0;vector-effect:non-scaling-stroke}.combined-hash-tooltip{position:absolute;z-index:9;pointer-events:none;min-width:180px;padding:9px 11px;border:1px solid #35503b;border-radius:8px;background:rgba(9,14,11,.97);box-shadow:0 8px 28px rgba(0,0,0,.35);font-size:11px;line-height:1.55;color:#e6efe7;transform:translate(-50%,-112%)}.hash-legend{display:flex;justify-content:center;gap:22px;flex-wrap:wrap;margin-top:9px;font-size:12px}.hash-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}.hash-dot.pool{background:#65c466}.hash-dot.net{background:#45a3ff}.hash-footer{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:8px;color:#718477;font-size:10px}@media(max-width:900px){.hash-metrics{grid-template-columns:repeat(2,minmax(130px,1fr))}}@media(max-width:560px){.hash-metrics{grid-template-columns:1fr}.combined-hash-chart{height:300px}}`;
    document.head.appendChild(s);
  }

  function bindHover(card,history,samples,networkNow){
    const svg=card.querySelector('.combined-hash-chart'),tip=card.querySelector('.combined-hash-tooltip'),cross=card.querySelector('.hash-crosshair');
    if(!svg||!tip||!cross||!history.length) return;
    const W=1120,L=72,R=78,minTs=Number(history[0].ts||0),maxTs=Number(history[history.length-1].ts||minTs+1);
    function show(clientX){
      const rect=svg.getBoundingClientRect(),sx=Math.max(L,Math.min(W-R,(clientX-rect.left)/rect.width*W)),ratio=(sx-L)/(W-L-R),target=minTs+(maxTs-minTs)*ratio;
      let best=history[0];for(const r of history){if(Math.abs(Number(r.ts)-target)<Math.abs(Number(best.ts)-target))best=r;}
      const pool=Number(best.hashrate||0),net=networkAt(samples,Number(best.ts),networkNow),share=net>0?pool/net*100:0,x=L+(Number(best.ts)-minTs)/Math.max(1,maxTs-minTs)*(W-L-R);
      cross.setAttribute('x1',x);cross.setAttribute('x2',x);cross.style.opacity='1';tip.hidden=false;
      tip.innerHTML=`<strong>${esc(new Date(Number(best.ts)*1000).toLocaleString())}</strong><br><span style="color:#80d985">Pool</span>: ${esc(hashRate(pool))}<br><span style="color:#6eb7ff">Network</span>: ${esc(hashRate(net))}<br>Pool share: ${share.toFixed(2)}%`;
      tip.style.left=`${(x/W)*100}%`;tip.style.top='58%';
    }
    svg.addEventListener('mousemove',e=>show(e.clientX));svg.addEventListener('mouseleave',()=>{tip.hidden=true;cross.style.opacity='0';});svg.addEventListener('touchmove',e=>{if(e.touches[0])show(e.touches[0].clientX);},{passive:true});
  }

  function bindRange(card){card.querySelectorAll('[data-range]').forEach(btn=>{btn.onclick=()=>{const next=btn.dataset.range;if(!RANGES[next]||next===selectedRange)return;selectedRange=next;render(true);};});}

  async function render(force=false){
    if(busy){pending=true;return;}
    const card=combinedCard();if(!card)return;busy=true;
    try{
      const r=RANGES[selectedRange];
      const [history,luck]=await Promise.all([get(`/api/pool/history?hours=${r.hours}&bucket=${r.bucket}&_=${Date.now()}`).catch(()=>[]),get(`/api/luck?_=${Date.now()}`).catch(()=>null)]);
      if(!history.length||!luck){card.innerHTML='<div class="hash-head"><div><h3>Network Hash vs Pool Hash</h3><div class="muted small">Hashrate history is temporarily unavailable.</div></div></div><div class="hash-loading">Waiting for hashrate data…</div>';return;}
      const difficulty=Number(luck.network_difficulty||0);
      const networkNow=Number(luck.network_hashrate||0) || (difficulty>0?difficulty*DIFF1_HASHES/BLOCK_TARGET_SECONDS:0);
      const poolNow=Number(luck.pool_hashrate||0);
      const allSamples=saveNetworkSample(networkNow),cutoff=Math.floor(Date.now()/1000)-r.hours*3600,samples=allSamples.filter(x=>Number(x.ts)>=cutoff);
      const poolVals=history.map(x=>Number(x.hashrate||0)),netVals=history.map(x=>networkAt(samples,Number(x.ts||0),networkNow)),p=calcStats(poolVals),n=calcStats(netVals),share=networkNow>0?poolNow/networkNow*100:0;
      styles();
      card.innerHTML=`<div class="hash-head"><div><h3>Network Hash vs Pool Hash</h3><div class="muted small">Pool and Yerbas network hashrate over the selected time range.</div></div><div class="hash-range">${Object.keys(RANGES).map(k=>`<button type="button" data-range="${k}" class="${k===selectedRange?'active':''}">${k}</button>`).join('')}</div></div><div class="hash-metrics"><div class="hash-metric"><span>Pool now</span><strong>${hashRate(poolNow)}</strong><small>${selectedRange} average ${hashRate(p.avg)}</small></div><div class="hash-metric"><span>Network now</span><strong>${hashRate(networkNow)}</strong><small>${selectedRange} average ${hashRate(n.avg)}</small></div><div class="hash-metric"><span>Pool share</span><strong>${share.toFixed(2)}%</strong><small>of current network hash</small></div><div class="hash-metric"><span>Peak pool</span><strong>${hashRate(p.peak)}</strong><small>${selectedRange} peak</small></div><div class="hash-metric"><span>Peak network</span><strong>${hashRate(n.peak)}</strong><small>${selectedRange} peak</small></div></div>${chart(history,samples,networkNow)}<div class="hash-legend"><span><i class="hash-dot pool"></i>Pool hashrate</span><span><i class="hash-dot net"></i>Network hashrate</span></div><div class="hash-footer"><span>Left scale: pool hashrate · Right scale: network hashrate</span><span>Updated ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span></div>`;
      bindRange(card);bindHover(card,history,samples,networkNow);
    }finally{busy=false;if(pending){pending=false;setTimeout(()=>render(true),0);}}
  }

  function install(){
    styles();const app=document.querySelector('main#app');let started=false;
    const start=()=>{const card=combinedCard();if(!card)return false;if(!started){started=true;render();}return true;};
    if(!start()&&app){const observer=new MutationObserver(()=>{if(start())observer.disconnect();});observer.observe(app,{childList:true,subtree:true});}
    setInterval(()=>render(),15000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})();