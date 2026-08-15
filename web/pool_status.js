(function(){
  let state={pool:null,health:null};
  let refreshBusy=false;

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
  }

  async function refresh(){
    if(refreshBusy) return;
    refreshBusy=true;
    try{
      const [poolResult,healthResult]=await Promise.allSettled([
        fetch('/api/pool',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error('pool status unavailable'))),
        fetch('/api/health',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error('health unavailable')))
      ]);
      if(poolResult.status==='fulfilled') state.pool=poolResult.value;
      if(healthResult.status==='fulfilled') state.health=healthResult.value;
      render();
    }finally{
      refreshBusy=false;
    }
  }

  function install(){
    ensureStyle();
    ensureStrip();
    render();
    refresh();
    setInterval(refresh,15000);
    setInterval(()=>{
      const payout=document.getElementById('status-payout');
      if(payout && state.pool) payout.textContent=formatCountdown(state.pool.next_payout_check_at);
    },1000);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
