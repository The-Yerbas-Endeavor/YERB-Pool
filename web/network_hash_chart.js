(function(){
  if(location.pathname!=='/') return;

  const BLOCK_TARGET_SECONDS=150;
  const DIFF1_HASHES=4294967296;
  let busy=false;

  function chartTarget(){
    const main=document.querySelector('main#app');
    if(!main) return null;
    const heading=[...main.querySelectorAll('.chart-card h3')]
      .find(h=>h.textContent.trim()==='Share Activity' || h.textContent.trim()==='Network vs Pool Hashrate');
    return heading?.closest('.chart-card')||null;
  }

  function primeCard(){
    const card=chartTarget();
    if(!card) return null;
    const heading=card.querySelector('h3');
    if(heading && heading.textContent.trim()==='Share Activity'){
      card.innerHTML='<h3>Network vs Pool Hashrate</h3><div class="muted small">24-hour pool estimate compared with the current Yerbas network hashrate reference.</div><div class="empty" style="margin-top:12px">Loading network and pool hashrate…</div>';
    }
    return card;
  }

  function svgChart(history,networkHashrate){
    const W=720,H=240,L=58,R=12,T=14,B=30,iw=W-L-R,ih=H-T-B;
    const values=history.map(x=>Number(x.hashrate||0));
    const max=Math.max(networkHashrate,...values,1);
    const px=i=>L+(history.length<=1?0:i/(history.length-1))*iw;
    const py=v=>T+ih-Number(v||0)/max*ih;
    const poolPoints=history.map((x,i)=>`${px(i).toFixed(1)},${py(x.hashrate).toFixed(1)}`).join(' ');
    const networkY=py(networkHashrate).toFixed(1);
    let grid='';
    for(let i=0;i<=4;i++){
      const y=T+ih*i/4,val=max*(1-i/4);
      grid+=`<line class="gridline" x1="${L}" y1="${y}" x2="${W-R}" y2="${y}"/><text x="4" y="${y+4}">${esc(hashRate(val))}</text>`;
    }
    const first=history[0]?.ts,last=history[history.length-1]?.ts;
    return `<svg class="chart network-pool-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<line class="network-hash-line" x1="${L}" y1="${networkY}" x2="${W-R}" y2="${networkY}"/><polyline class="pool-hash-line" points="${poolPoints}"/><text x="${L}" y="${H-7}">${first?new Date(first*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):''}</text><text text-anchor="end" x="${W-R}" y="${H-7}">${last?new Date(last*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):''}</text></svg>`;
  }

  function ensureStyles(){
    if(document.getElementById('network-pool-chart-styles')) return;
    const style=document.createElement('style');
    style.id='network-pool-chart-styles';
    style.textContent=`
      .network-pool-chart .pool-hash-line{fill:none;stroke:var(--yerb,#65c466);stroke-width:2}
      .network-pool-chart .network-hash-line{fill:none;stroke:#74c0fc;stroke-width:2;stroke-dasharray:7 5}
      .network-pool-legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;font-size:12px}
      .network-pool-legend .network-dot{background:#74c0fc}
      .network-pool-values{display:flex;gap:18px;flex-wrap:wrap;margin-top:7px;font-size:12px;color:#9caf9d}
      .network-pool-values strong{color:#e9f7ea}
    `;
    document.head.appendChild(style);
  }

  async function render(){
    if(busy) return;
    const card=primeCard();
    if(!card) return;
    busy=true;
    try{
      const [history,luck]=await Promise.all([
        get('/api/pool/history?hours=24&bucket=300').catch(()=>[]),
        get('/api/luck').catch(()=>null)
      ]);
      if(!history.length || !luck) return;
      const difficulty=Number(luck.network_difficulty||0);
      const networkHashrate=difficulty>0 ? difficulty*DIFF1_HASHES/BLOCK_TARGET_SECONDS : 0;
      const poolHashrate=Number(luck.pool_hashrate||0);
      ensureStyles();
      card.innerHTML=`<h3>Network vs Pool Hashrate</h3><div class="muted small">24-hour pool estimate compared with the current Yerbas network hashrate reference.</div><div class="network-pool-values"><span>Pool now <strong>${hashRate(poolHashrate)}</strong></span><span>Network now <strong>${hashRate(networkHashrate)}</strong></span></div>${svgChart(history,networkHashrate)}<div class="network-pool-legend"><span><i class="dot hashdot"></i>Pool hashrate</span><span><i class="dot network-dot"></i>Current network reference</span></div>`;
    }finally{
      busy=false;
    }
  }

  async function install(){
    for(let i=0;i<30;i++){
      if(primeCard()) break;
      await new Promise(r=>setTimeout(r,25));
    }
    render();
    setInterval(render,15000);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
