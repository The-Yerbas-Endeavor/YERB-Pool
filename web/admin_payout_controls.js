(function(){
  if(location.pathname!=='/admin') return;

  let state=null;
  let busy=false;

  function placeTreasuryLast(){
    const main=document.querySelector('main');
    if(!main) return;
    const payoutConfig=[...main.querySelectorAll('section')].find(s=>s.querySelector('h2')?.textContent.trim()==='Payout configuration');
    const treasury=[...main.querySelectorAll('section')].find(s=>s.querySelector('h2')?.textContent.trim()==='Pool Treasury');
    if(payoutConfig && treasury && payoutConfig.nextElementSibling!==treasury){
      payoutConfig.insertAdjacentElement('afterend',treasury);
    }
  }

  function limitTreasuryActivity(){
    const root=document.getElementById('treasury-activity');
    if(!root) return;
    const rows=[...root.querySelectorAll('tbody tr')];
    rows.slice(10).forEach(row=>row.remove());
  }

  function ensurePanel(){
    if(document.getElementById('admin-payout-controls')){
      placeTreasuryLast();
      limitTreasuryActivity();
      return;
    }
    const main=document.querySelector('main');
    if(!main) return;
    const section=document.createElement('section');
    section.id='admin-payout-controls';
    section.innerHTML=`
      <h2>Payout controls</h2>
      <div class="admin-card">
        <div class="admin-grid" id="payout-control-status">
          <div><span class="muted">Scheduler</span><strong>Loading…</strong></div>
        </div>
        <div class="form-row" style="margin-top:20px">
          <button id="payout-run-now" type="button">Run payout check now</button>
          <button id="payout-pause-toggle" type="button">Pause payouts</button>
        </div>
        <p class="muted">Pausing stops miner payout checks only. Block confirmation and maturity processing continues normally.</p>
        <div id="payout-control-message"></div>
      </div>`;
    const payoutConfig=[...main.querySelectorAll('section')].find(s=>s.querySelector('h2')?.textContent.trim()==='Payout configuration');
    if(payoutConfig) payoutConfig.insertAdjacentElement('beforebegin',section);
    else main.appendChild(section);
    section.querySelector('#payout-run-now').addEventListener('click',runNow);
    section.querySelector('#payout-pause-toggle').addEventListener('click',togglePause);
    placeTreasuryLast();
    limitTreasuryActivity();
  }

  function fmtTime(epoch){
    const n=Number(epoch||0);
    return n?new Date(n*1000).toLocaleString():'—';
  }

  function countdown(epoch){
    const target=Number(epoch||0);
    if(!target) return '—';
    let seconds=Math.max(0,Math.floor(target-Date.now()/1000));
    const h=Math.floor(seconds/3600); seconds%=3600;
    const m=Math.floor(seconds/60); const s=seconds%60;
    return h>0?`${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`:`${m}m ${String(s).padStart(2,'0')}s`;
  }

  function render(){
    ensurePanel();
    if(!state) return;
    const root=document.getElementById('payout-control-status');
    const run=document.getElementById('payout-run-now');
    const pause=document.getElementById('payout-pause-toggle');
    if(!root || !run || !pause) return;

    const request=state.request||{};
    const running=request.state==='queued'||request.state==='running';
    const schedulerLabel=!state.enabled?'Disabled':state.paused?'Paused':'Active';
    root.innerHTML=`
      <div><span class="muted">Scheduler</span><strong>${schedulerLabel}</strong></div>
      <div><span class="muted">Next scheduled payout</span><strong style="font-size:18px">${state.paused?'Paused':countdown(state.next_check_at)}</strong><span class="muted" style="display:block;margin-top:4px">${state.paused?'No automatic payout while paused':fmtTime(state.next_check_at)}</span></div>
      <div><span class="muted">Last payout check</span><strong style="font-size:18px">${fmtTime(state.last_check_at)}</strong></div>
      <div><span class="muted">Last result</span><strong style="font-size:18px">${state.last_result||'waiting'}</strong></div>
      <div><span class="muted">Manual request</span><strong style="font-size:18px">${request.state||'idle'}</strong></div>`;

    run.disabled=busy || running || state.paused || !state.enabled;
    run.style.opacity=run.disabled?'.55':'1';
    pause.disabled=busy || !state.enabled;
    pause.style.opacity=pause.disabled?'.55':'1';
    pause.textContent=state.paused?'Resume payouts':'Pause payouts';
    placeTreasuryLast();
    limitTreasuryActivity();
  }

  async function refresh(){
    try{
      const r=await fetch('/api/admin/payouts/control',{cache:'no-store'});
      const x=await r.json();
      if(!r.ok) throw new Error(x.error||'Unable to load payout controls');
      state=x;
      render();
    }catch(e){
      ensurePanel();
      const message=document.getElementById('payout-control-message');
      if(message){message.className='error';message.textContent=e.message;}
    }
  }

  async function runNow(){
    if(busy) return;
    if(!confirm('Run the payout check now? Eligible miners may be paid immediately.')) return;
    busy=true; render();
    const message=document.getElementById('payout-control-message');
    if(message){message.className='';message.textContent='Queueing payout check…';}
    try{
      const r=await fetch('/api/admin/payouts/run-now',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      const x=await r.json();
      if(!r.ok) throw new Error(x.error||'Unable to queue payout check');
      if(message){message.className='notice';message.textContent='Payout check queued. The pool daemon will run it through the normal payout engine.';}
    }catch(e){
      if(message){message.className='error';message.textContent=e.message;}
    }finally{
      busy=false;
      await refresh();
    }
  }

  async function togglePause(){
    if(busy || !state) return;
    const paused=!state.paused;
    if(paused && !confirm('Pause miner payouts? Block maturity processing will continue.')) return;
    busy=true; render();
    const message=document.getElementById('payout-control-message');
    try{
      const r=await fetch('/api/admin/payouts/pause',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paused})});
      const x=await r.json();
      if(!r.ok) throw new Error(x.error||'Unable to update payout state');
      if(message){message.className='notice';message.textContent=paused?'Payouts paused.':'Payouts resumed.';}
    }catch(e){
      if(message){message.className='error';message.textContent=e.message;}
    }finally{
      busy=false;
      await refresh();
    }
  }

  function install(){
    ensurePanel();
    const treasuryActivity=document.getElementById('treasury-activity');
    if(treasuryActivity){
      new MutationObserver(limitTreasuryActivity).observe(treasuryActivity,{childList:true,subtree:true});
    }
    refresh();
    setInterval(refresh,5000);
    setInterval(render,1000);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
