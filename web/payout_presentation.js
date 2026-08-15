(function(){
  if(location.pathname!=='/') return;

  let busy=false;

  function ensureStyles(){
    if(document.getElementById('yerb-payout-card-styles')) return;
    const style=document.createElement('style');
    style.id='yerb-payout-card-styles';
    style.textContent=`
      .payout-status{display:inline-block;padding:3px 8px;border-radius:999px;border:1px solid transparent;font-size:11px;font-weight:700;text-transform:capitalize}
      .payout-status-sent{color:#8ee889;background:rgba(101,196,102,.13);border-color:rgba(101,196,102,.38)}
      .payout-status-pending,.payout-status-broadcasting{color:#ffe066;background:rgba(255,224,102,.12);border-color:rgba(255,224,102,.36)}
      .payout-status-failed,.payout-status-uncertain{color:#ff8787;background:rgba(255,107,107,.12);border-color:rgba(255,107,107,.36)}
      #home-panel-row .recent-payouts-card table th,
      #home-panel-row .recent-payouts-card table td{padding:8px 6px;font-size:12px}
      #home-panel-row .recent-payouts-card .payout-age{color:#91a394;font-size:11px;white-space:nowrap}
    `;
    document.head.appendChild(style);
  }

  function payoutBadge(value){
    const status=String(value||'').toLowerCase();
    const cls=['sent','pending','broadcasting','failed','uncertain'].includes(status)?status:'pending';
    return `<span class="payout-status payout-status-${cls}">${esc(value||'pending')}</span>`;
  }

  function age(ts){
    if(!ts) return '—';
    const seconds=Math.max(0,Math.floor(Date.now()/1000-Number(ts)));
    if(seconds<60) return `${seconds}s ago`;
    if(seconds<3600) return `${Math.floor(seconds/60)}m ago`;
    if(seconds<86400) return `${Math.floor(seconds/3600)}h ago`;
    return `${Math.floor(seconds/86400)}d ago`;
  }

  function findHomeMinersSection(){
    const row=document.getElementById('home-panel-row');
    if(!row) return null;
    const heading=[...row.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Miners');
    return heading?.closest('section')||null;
  }

  async function render(){
    if(busy || location.pathname!=='/') return;
    const section=findHomeMinersSection();
    if(!section) return;
    busy=true;
    try{
      const payouts=await get('/api/payouts?limit=5').catch(()=>[]);
      if(!document.body.contains(section)) return;
      ensureStyles();
      section.classList.add('recent-payouts-card');
      const body=payouts.length
        ? table(['Batch','Status','Total','Recipients','Age'],payouts.slice(0,5).map(p=>`<tr><td><a href="/payouts#${encodeURIComponent(p.id)}">#${p.id}</a></td><td>${payoutBadge(p.status)}</td><td>${coin(p.total_atomic)} YERB</td><td>${Number(p.recipient_count||0).toLocaleString()}</td><td class="payout-age">${age(p.sent_at||p.created_at)}</td></tr>`))
        : '<div class="empty">No payouts yet.</div>';
      section.innerHTML=`<div class="section-head"><h2>Recent Payouts</h2><a href="/payouts">View all →</a></div>${body}`;
    }finally{
      busy=false;
    }
  }

  async function install(){
    ensureStyles();
    for(let i=0;i<20;i++){
      if(findHomeMinersSection()) break;
      await new Promise(r=>setTimeout(r,150));
    }
    render();
    setInterval(render,15000);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
