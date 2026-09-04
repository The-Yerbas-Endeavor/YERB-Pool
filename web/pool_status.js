(function(){
  let state={pool:null,health:null,summary:null,activeMiners:null};
  let refreshBusy=false;
  let workerShareTimer=null;
  let workerLastShareAt=0;
  let dashboardMinerObserver=null;

  function ensureStyle(){
    if(document.getElementById('yerb-pool-status-style')) return;
    const style=document.createElement('style');
    style.id='yerb-pool-status-style';
    style.textContent=`
      body{
        padding-bottom:48px!important;
      }
      #yerb-pool-status{
        position:fixed;
        left:0;
        right:0;
        bottom:0;
        z-index:1000;
        border-top:1px solid #29352d;
        background:rgba(18,23,19,.97);
        box-shadow:0 -8px 24px rgba(0,0,0,.18);
        backdrop-filter:blur(8px);
        -webkit-backdrop-filter:blur(8px);
      }
      #yerb-pool-status .status-inner{
        max-width:1600px;
        margin:auto;
        padding:9px 24px;
        display:flex;
        align-items:center;
        gap:16px;
        flex-wrap:wrap;
        font-size:12px;
        color:#b9c7bc;
      }
      #yerb-pool-status .status-item{
        display:inline-flex;
        gap:6px;
        align-items:center;
        white-space:nowrap;
      }
      #yerb-pool-status .status-dot{
        width:8px;
        height:8px;
        border-radius:50%;
        display:inline-block;
        background:#777;
        box-shadow:0 0 0 2px rgba(255,255,255,.03);
      }
      #yerb-pool-status .status-dot.ok{background:#65c466}
      #yerb-pool-status .status-dot.warn{background:#e5b94c}
      #yerb-pool-status .status-dot.bad{background:#e06b6b}
      #yerb-pool-status a{color:inherit;text-decoration:none}
      #yerb-pool-status a:hover{text-decoration:underline}
      #yerb-pool-status .status-spacer{flex:1}
      #worker-hash-card .hash-metrics{grid-template-columns:repeat(4,minmax(130px,1fr))!important}
      @media(max-width:900px){#worker-hash-card .hash-metrics{grid-template-columns:repeat(2,minmax(130px,1fr))!important}}
      @media(max-width:520px){#worker-hash-card .hash-metrics{grid-template-columns:1fr!important}}
      @media(max-width:700px){
        body{padding-bottom:74px!important}
        #yerb-pool-status .status-inner{
          padding:8px 14px;
          gap:7px 12px;
          justify-content:center;
          font-size:11px;
        }
        #yerb-pool-status .status-spacer{display:none}
      }
      @media(max-width:430px){
        body{padding-bottom:92px!important}
        #yerb-pool-status .status-inner{gap:6px 10px}
      }
    `;
    document.head.appendChild(style);
  }

  function ensureStrip(){
    let root=document.getElementById('yerb-pool-status');
    if(root) return root;
    if(!document.body) return null;
    root=document.createElement('div');
    root.id='yerb-pool-status';
    root.setAttribute('role','status');
    root.setAttribute('aria-label','YERB Pool live status');
    root.innerHTML=`<div class="status-inner">
      <span class="status-item"><i id="status-stratum-dot" class="status-dot"></i><span id="status-stratum">Stratum checking…</span></span>
      <span class="status-item"><i id="status-wallet-dot" class="status-dot"></i><span id="status-wallet">Wallet checking…</span></span>
      <span class="status-item"><i id="status-accounting-dot" class="status-dot"></i><span id="status-accounting">Accounting checking…</span></span>
      <span class="status-spacer"></span>
      <a class="status-item" href="/workers"><strong id="status-workers">0</strong>&nbsp;active workers</a>
      <span class="status-item">Fee <strong id="status-fee">—</strong></span>
      <a class="status-item" href="/payouts">Next payout <strong id="status-payout">—</strong></a>
    </div>`;
    document.body.appendChild(root);
    return root;
  }

  function setHealth(id,label,online,warning){
    const text=document.getElementById(id);
    const dot=document.getElementById(id+'-dot');
    if(text) text.textContent=label;
    if(dot){
      dot.className='status-dot '+(online?'ok':warning?'warn':'bad');
    }
  }

  function formatCountdown(epoch){
    const target=Number(epoch||0);
    if(!target) return 'every 2h';
    const left=Math.max(0,Math.floor(target-Date.now()/1000));
    if(left<=0) return 'checking…';
    const h=Math.floor(left/3600);
    const m=Math.floor((left%3600)/60);
    const s=left%60;
    if(h>0) return `${h}h ${String(m).padStart(2,'0')}m`;
    return `${m}m ${String(s).padStart(2,'0')}s`;
  }

  function formatSince(epoch){
    const t=Number(epoch||0);
    if(!t) return 'Never';
    const age=Math.max(0,Math.floor(Date.now()/1000-t));
    if(age<60) return `${age}s ago`;
    if(age<3600){
      const m=Math.floor(age/60),s=age%60;
      return `${m}m ${String(s).padStart(2,'0')}s ago`;
    }
    if(age<86400){
      const h=Math.floor(age/3600),m=Math.floor((age%3600)/60);
      return `${h}h ${String(m).padStart(2,'0')}m ago`;
    }
    const d=Math.floor(age/86400),h=Math.floor((age%86400)/3600);
    return `${d}d ${h}h ago`;
  }

  function dashboardMinerCards(){
    if(location.pathname!=='/') return [];
    return [...document.querySelectorAll('#combined-hash-card .hash-metric')].filter(el=>{
      const label=el.querySelector('span')?.textContent?.trim();
      const detail=el.querySelector('small')?.textContent?.trim();
      return label==='Miners' || label==='Active miners' || detail==='tracked payout addresses';
    });
  }

  function activeMinerCount(){
    if(state.activeMiners!=null) return Number(state.activeMiners||0);
    const summaryCount=state.summary?.accounts?.active_miners;
    return summaryCount==null?null:Number(summaryCount||0);
  }

  function ensureDashboardActiveMinerCard(){
    if(location.pathname!=='/') return null;
    const cards=dashboardMinerCards();
    if(cards.length){
      for(const duplicate of cards.slice(1)) duplicate.remove();
      return cards[0];
    }
    const metrics=document.querySelector('#combined-hash-card .hash-metrics');
    if(!metrics) return null;
    const card=document.createElement('div');
    card.className='hash-metric';
    card.innerHTML='<span>Active miners</span><strong>—</strong><small>active within the last hour</small>';
    const blockCard=[...metrics.querySelectorAll('.hash-metric')].find(el=>el.querySelector('span')?.textContent?.trim()==='Block ETA / Last found');
    if(blockCard) metrics.insertBefore(card,blockCard);
    else metrics.appendChild(card);
    return card;
  }

  function hideStaleDashboardMiners(){
    const card=ensureDashboardActiveMinerCard();
    if(!card) return;
    if(activeMinerCount()==null) card.style.visibility='hidden';
  }

  function updateDashboardActiveMiners(){
    if(location.pathname!=='/') return;
    const active=activeMinerCount();
    const card=ensureDashboardActiveMinerCard();
    if(!card) return;
    if(active==null){
      card.style.visibility='hidden';
      return;
    }
    const label=card.querySelector('span');
    const value=card.querySelector('strong');
    const detail=card.querySelector('small');
    if(label) label.textContent='Active miners';
    if(value) value.textContent=Number(active).toLocaleString();
    if(detail) detail.textContent='active within the last hour';
    card.style.visibility='';
  }

  function watchDashboardMinerCard(){
    if(location.pathname!=='/' || dashboardMinerObserver || !document.body) return;
    dashboardMinerObserver=new MutationObserver(()=>{
      if(activeMinerCount()==null) hideStaleDashboardMiners();
      else updateDashboardActiveMiners();
    });
    dashboardMinerObserver.observe(document.body,{childList:true,subtree:true});
    hideStaleDashboardMiners();
  }

  function mergeWorkerShareCards(){
    if(!location.pathname.startsWith('/worker/')) return;
    const metrics=document.querySelector('#worker-hash-card .hash-metrics');
    if(!metrics) return;
    const cards=[...metrics.querySelectorAll('.hash-metric')];
    const accepted=cards.find(card=>card.querySelector('span')?.textContent.trim()==='Accepted');
    const rejected=cards.find(card=>card.querySelector('span')?.textContent.trim()==='Rejected');
    if(!accepted||!rejected) return;

    const acceptedValue=accepted.querySelector('strong')?.textContent.trim()||'0';
    const rejectedValue=rejected.querySelector('strong')?.textContent.trim()||'0';
    const rejectDetail=rejected.querySelector('small')?.textContent.trim()||'';
    accepted.querySelector('span').textContent='Accepted / Rejected';
    accepted.querySelector('strong').textContent=`${acceptedValue} / ${rejectedValue}`;
    const detail=accepted.querySelector('small');
    if(detail) detail.textContent=rejectDetail ? `accepted / rejected · ${rejectDetail}` : 'accepted / rejected';
    rejected.remove();
  }

  function renderWorkerLastShare(){
    if(!location.pathname.startsWith('/worker/')) return;
    const metrics=document.querySelector('#worker-hash-card .hash-metrics');
    if(!metrics) return;
    mergeWorkerShareCards();
    let card=document.getElementById('worker-last-share-card');
    if(!card){
      card=document.createElement('div');
      card.id='worker-last-share-card';
      card.className='hash-metric';
      card.innerHTML='<span>Last share submitted</span><strong id="worker-last-share-value">—</strong><small id="worker-last-share-time">waiting for share data</small>';
      const efficiency=[...metrics.querySelectorAll('.hash-metric')].find(x=>x.querySelector('span')?.textContent.trim()==='Efficiency');
      if(efficiency) metrics.insertBefore(card,efficiency);
      else metrics.appendChild(card);
    }
    const value=document.getElementById('worker-last-share-value');
    const detail=document.getElementById('worker-last-share-time');
    if(value) value.textContent=formatSince(workerLastShareAt);
    if(detail){
      detail.textContent=workerLastShareAt
        ? new Date(workerLastShareAt*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})
        : 'no submitted share recorded';
    }
  }

  async function refreshWorkerLastShare(){
    if(!location.pathname.startsWith('/worker/')) return;
    const id=location.pathname.slice('/worker/'.length);
    if(!id) return;
    try{
      const r=await fetch(`/api/worker/${encodeURIComponent(id)}/stats?hours=1&bucket=60`,{cache:'no-store'});
      if(r.ok){
        const data=await r.json();
        workerLastShareAt=Number(data.last_share_at||0);
      }
    }catch(_){}
    renderWorkerLastShare();
  }

  function setHealthWorkerTimer(){
    if(!location.pathname.startsWith('/worker/')) return;
    refreshWorkerLastShare();
    if(workerShareTimer) return;
    workerShareTimer=setInterval(()=>{
      renderWorkerLastShare();
    },1000);
    setInterval(refreshWorkerLastShare,15000);
  }

  function render(){
    ensureStyle();
    if(!ensureStrip()) return;
    const p=state.pool||{};
    const h=state.health||{};

    const stratum=h.stratum||{};
    setHealth('status-stratum',stratum.online?'Stratum Online':'Stratum Offline',!!stratum.online,false);

    const wallet=h.wallet||{};
    setHealth('status-wallet',wallet.online?'Wallet Online':'Wallet Offline',!!wallet.online,false);

    const accounting=h.accounting||{};
    if(accounting.ok===true){
      setHealth('status-accounting','Accounting OK',true,false);
    }else if(accounting.ok===false){
      setHealth('status-accounting','Accounting Check',false,true);
    }else{
      setHealth('status-accounting','Accounting —',false,true);
    }

    const workers=document.getElementById('status-workers');
    if(workers) workers.textContent=Number(p.active_workers||0).toLocaleString();
    const fee=document.getElementById('status-fee');
    if(fee) fee.textContent=Number(p.pool_fee_percent||0).toFixed(2)+'%';
    const payout=document.getElementById('status-payout');
    if(payout) payout.textContent=formatCountdown(p.next_payout_check_at);
    updateDashboardActiveMiners();
    renderWorkerLastShare();
  }

  async function refresh(){
    if(refreshBusy) return;
    refreshBusy=true;
    try{
      const [poolResult,healthResult,summaryResult,minersResult]=await Promise.allSettled([
        fetch('/api/pool',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error('pool status unavailable'))),
        fetch('/api/health',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error('health unavailable'))),
        fetch('/api/summary',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error('summary unavailable'))),
        fetch('/api/miners?limit=1000',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error('miners unavailable')))
      ]);
      if(poolResult.status==='fulfilled') state.pool=poolResult.value;
      if(healthResult.status==='fulfilled') state.health=healthResult.value;
      if(summaryResult.status==='fulfilled') state.summary=summaryResult.value;
      if(minersResult.status==='fulfilled'){
        const miners=minersResult.value;
        state.activeMiners=Array.isArray(miners)?miners.length:(Array.isArray(miners?.items)?miners.items.length:null);
      }
      render();
    }finally{
      refreshBusy=false;
    }
  }

  function install(){
    ensureStyle();
    ensureStrip();
    watchDashboardMinerCard();
    hideStaleDashboardMiners();
    render();
    refresh();
    setHealthWorkerTimer();
    setInterval(refresh,15000);
    setInterval(()=>{
      const payout=document.getElementById('status-payout');
      if(payout && state.pool) payout.textContent=formatCountdown(state.pool.next_payout_check_at);
    },1000);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();