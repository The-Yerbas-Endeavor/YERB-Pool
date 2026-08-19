(function(){
  const HOME=location.pathname==='/';
  const PAYOUTS=location.pathname==='/payouts';
  if(!HOME && !PAYOUTS) return;

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
      .recent-payouts-card{display:flex;flex-direction:column;height:100%}
      .recent-payouts-card .payout-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:10px 0 4px}
      .recent-payouts-card .payout-summary-item{padding:8px 9px;border:1px solid rgba(101,196,102,.20);border-radius:7px;background:rgba(101,196,102,.04)}
      .recent-payouts-card .payout-summary-item span{display:block;color:#91a394;font-size:10px;margin-bottom:2px}
      .recent-payouts-card .payout-summary-item strong{font-size:13px;color:#e9f7ea}
      .recent-payouts-card .table-wrap{flex:1}
      .recent-payouts-card table th,
      .recent-payouts-card table td{padding:5px 6px;font-size:11px}
      .recent-payouts-card .payout-age{color:#91a394;font-size:10px;white-space:nowrap}
      .home-miners-compat-marker{display:none!important}
      .payout-detail{max-width:1100px;margin:0 auto}
      .payout-detail .detail-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
      .payout-detail .detail-head h2{margin-bottom:4px}
      .payout-detail .detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px}
      .payout-detail .detail-card{padding:15px;border:1px solid rgba(101,196,102,.20);border-radius:9px;background:linear-gradient(155deg,#171d18,#141714)}
      .payout-detail .detail-card span{display:block;color:#91a394;font-size:12px;margin-bottom:5px}
      .payout-detail .detail-card strong{font-size:18px;color:#e9f7ea;word-break:break-word}
      .payout-detail .tx-card{margin-top:12px;padding:14px;border:1px solid rgba(101,196,102,.20);border-radius:9px;background:#111712}
      .payout-detail .tx-card code{word-break:break-all}
      .payout-detail .recipient-total{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:12px;padding:12px 14px;border-top:1px solid rgba(101,196,102,.18)}
      .payout-detail .detail-error{margin-top:12px;padding:12px 14px;border:1px solid rgba(255,107,107,.35);border-radius:8px;background:rgba(255,107,107,.08);color:#ffb3b3}
      @media(max-width:700px){.payout-detail .detail-grid{grid-template-columns:1fr 1fr}.payout-detail table td,.payout-detail table th{font-size:12px;padding:8px 6px}}
      @media(max-width:480px){.payout-detail .detail-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function payoutBadge(value){
    const valueText=String(value||'pending');
    const status=valueText.toLowerCase();
    const cls=['sent','pending','broadcasting','failed','uncertain'].includes(status)?status:'pending';
    return `<span class="payout-status payout-status-${cls}">${esc(valueText)}</span>`;
  }

  function age(ts){
    if(!ts) return '—';
    const seconds=Math.max(0,Math.floor(Date.now()/1000-Number(ts)));
    if(seconds<60) return `${seconds}s ago`;
    if(seconds<3600) return `${Math.floor(seconds/60)}m ago`;
    if(seconds<86400) return `${Math.floor(seconds/3600)}h ago`;
    return `${Math.floor(seconds/86400)}d ago`;
  }

  function homeRow(){
    return document.getElementById('home-panel-row') || document.querySelector('main#app');
  }

  function headingSection(label,root=document){
    const heading=[...root.querySelectorAll('h2')].find(h=>h.textContent.trim()===label);
    return heading?.closest('section')||null;
  }

  function findTargetSection(){
    const row=homeRow();
    if(!row) return null;
    return headingSection('Recent Payouts',row) || headingSection('Miners',row);
  }

  function enforceThreeCardRow(keep){
    const main=document.querySelector('main#app');
    const row=homeRow();
    if(!main || !row || !keep) return;

    const blocks=headingSection('Recent Blocks',row);
    if(keep.parentNode!==row){
      if(blocks) blocks.insertAdjacentElement('afterend',keep);
      else row.appendChild(keep);
    }

    [...main.querySelectorAll('section')].forEach(section=>{
      if(section===keep) return;
      const heading=section.querySelector(':scope > .section-head h2, :scope > h2');
      if(!heading) return;
      const label=heading.textContent.trim();
      if(label==='Miners' || label==='Recent Payouts') section.remove();
    });

    row.classList.add('payout-ready');
  }

  async function renderHome(){
    if(busy || !HOME) return;
    const section=findTargetSection();
    if(!section) return;
    busy=true;
    try{
      const payouts=await get('/api/payouts?limit=10').catch(()=>[]);
      if(!document.body.contains(section)) return;
      ensureStyles();
      section.classList.add('recent-payouts-card');

      const shown=payouts.slice(0,10);
      const now=Math.floor(Date.now()/1000);
      const last24=shown.filter(p=>Number(p.sent_at||p.created_at||0)>=now-86400 && String(p.status||'').toLowerCase()==='sent');
      const paid24=last24.reduce((n,p)=>n+Number(p.total_atomic||0),0);
      const recipients24=last24.reduce((n,p)=>n+Number(p.recipient_count||0),0);
      const avg24=last24.length?paid24/last24.length:0;

      const summary=`<div class="payout-summary"><div class="payout-summary-item"><span>Paid / 24h</span><strong>${coin(paid24)} YERB</strong></div><div class="payout-summary-item"><span>Batches / 24h</span><strong>${last24.length.toLocaleString()}</strong></div><div class="payout-summary-item"><span>Recipients / 24h</span><strong>${recipients24.toLocaleString()}</strong></div><div class="payout-summary-item"><span>Average batch</span><strong>${coin(avg24)} YERB</strong></div></div>`;

      const body=shown.length
        ? table(['Batch','Status','Total','Recipients','Age'],shown.map(p=>`<tr><td><a href="/payouts?id=${encodeURIComponent(p.id)}">#${p.id}</a></td><td>${payoutBadge(p.status)}</td><td>${coin(p.total_atomic)} YERB</td><td>${Number(p.recipient_count||0).toLocaleString()}</td><td class="payout-age">${age(p.sent_at||p.created_at)}</td></tr>`))
        : '<div class="empty">No payouts yet.</div>';

      section.innerHTML=`<h2 class="home-miners-compat-marker" aria-hidden="true">Miners</h2><div class="section-head"><h2>Recent Payouts</h2><a href="/payouts">View all →</a></div>${summary}${body}`;
      enforceThreeCardRow(section);
    }finally{
      busy=false;
    }
  }

  function rewriteHistoryLinks(){
    if(!PAYOUTS || new URLSearchParams(location.search).has('id')) return;
    const root=document.querySelector('main#app');
    if(!root) return;
    root.querySelectorAll('a[href^="/payouts#"]').forEach(link=>{
      const id=(link.getAttribute('href')||'').split('#')[1];
      if(id) link.href=`/payouts?id=${encodeURIComponent(id)}`;
    });
  }

  async function payoutRecipients(batchId){
    const miners=await get('/api/miners?limit=1000').catch(()=>[]);
    const accounts=await Promise.all(miners.map(miner=>
      get('/api/account/'+encodeURIComponent(miner.address)).catch(()=>null)
    ));
    const recipients=[];
    for(const account of accounts){
      if(!account) continue;
      const item=(account.payouts||[]).find(p=>Number(p.id)===Number(batchId));
      if(item) recipients.push({address:account.address,amount_atomic:Number(item.amount_atomic||0)});
    }
    recipients.sort((a,b)=>b.amount_atomic-a.amount_atomic || a.address.localeCompare(b.address));
    return recipients;
  }

  async function renderDetail(batchId){
    ensureStyles();
    const root=document.querySelector('main#app');
    if(!root) return;
    root.innerHTML='<section class="payout-detail"><a class="back" href="/payouts">← Payouts</a><div class="empty">Loading payout batch…</div></section>';

    const payouts=await get('/api/payouts?limit=100').catch(()=>[]);
    const batch=payouts.find(p=>Number(p.id)===Number(batchId));
    if(!batch){
      root.innerHTML='<section class="payout-detail"><a class="back" href="/payouts">← Payouts</a><div class="empty bad">Payout batch not found.</div></section>';
      return;
    }

    const recipients=await payoutRecipients(batchId);
    const recipientsTotal=recipients.reduce((sum,r)=>sum+Number(r.amount_atomic||0),0);
    const tx=batch.txid
      ? `<a href="${EXPLORER}/tx/${encodeURIComponent(batch.txid)}" target="_blank" rel="noopener"><code>${esc(batch.txid)}</code></a>`
      : '<span class="muted">Not available</span>';
    const error=batch.error?`<div class="detail-error"><strong>Error:</strong> ${esc(batch.error)}</div>`:'';
    const recipientRows=recipients.length
      ? table(['Recipient','Amount'],recipients.map(r=>`<tr><td><a href="/account/${encodeURIComponent(r.address)}"><code>${esc(r.address)}</code></a></td><td>${coin(r.amount_atomic)} YERB</td></tr>`))
      : '<div class="empty">No recipient records were found for this batch.</div>';

    root.innerHTML=`<section class="payout-detail"><a class="back" href="/payouts">← Payouts</a><div class="detail-head"><div><h2>Payout Batch #${batch.id}</h2><div class="muted">Combined miner payout batch</div></div>${payoutBadge(batch.status)}</div><div class="detail-grid"><div class="detail-card"><span>Total</span><strong>${coin(batch.total_atomic)} YERB</strong></div><div class="detail-card"><span>Recipients</span><strong>${recipients.length || Number(batch.recipient_count||0)}</strong></div><div class="detail-card"><span>Created</span><strong style="font-size:14px">${when(batch.created_at)}</strong></div><div class="detail-card"><span>Sent</span><strong style="font-size:14px">${when(batch.sent_at)}</strong></div></div><div class="tx-card"><div class="muted small" style="margin-bottom:5px">Transaction ID</div>${tx}</div>${error}</section><section class="payout-detail"><div class="section-head"><h2>Recipients</h2><span class="muted">${recipients.length.toLocaleString()} recipient${recipients.length===1?'':'s'}</span></div>${recipientRows}<div class="recipient-total"><strong>Recipient total</strong><strong>${coin(recipientsTotal)} YERB</strong></div></section>`;
  }

  async function installHome(){
    ensureStyles();
    for(let i=0;i<30;i++){
      if(findTargetSection()) break;
      await new Promise(r=>setTimeout(r,100));
    }
    await renderHome();

    const main=document.querySelector('main#app');
    if(main){
      let scheduled=false;
      new MutationObserver(()=>{
        if(scheduled) return;
        scheduled=true;
        setTimeout(()=>{
          scheduled=false;
          const miners=[...main.querySelectorAll('h2')].some(h=>
            h.textContent.trim()==='Miners' && !h.classList.contains('home-miners-compat-marker')
          );
          const payouts=[...main.querySelectorAll('h2')].some(h=>h.textContent.trim()==='Recent Payouts');
          if(miners || !payouts) renderHome();
        },0);
      }).observe(main,{childList:true});
    }

    // Refresh the complete homepage once per minute. dashboard() redraws the
    // hashrate graphs, Top Workers, and Recent Blocks; renderHome() then
    // restores/refreshes the Recent Payouts card with current data.
    setInterval(async()=>{
      if(location.pathname!=='/' || busy) return;
      try{
        if(typeof dashboard==='function') await dashboard();
        await renderHome();
      }catch(_){ }
    },60000);
  }

  async function installPayouts(){
    ensureStyles();
    const id=(new URLSearchParams(location.search).get('id')||'').trim();
    if(id){
      await renderDetail(id);
      return;
    }
    for(let i=0;i<30;i++){
      rewriteHistoryLinks();
      if(document.querySelector('main#app table')) break;
      await new Promise(r=>setTimeout(r,100));
    }
    rewriteHistoryLinks();
    const root=document.querySelector('main#app');
    if(root){
      new MutationObserver(rewriteHistoryLinks).observe(root,{childList:true,subtree:true});
    }
  }

  function install(){
    if(HOME) installHome();
    else if(PAYOUTS) installPayouts();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
