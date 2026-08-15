(function(){
  if(location.pathname!=='/admin') return;

  let currentType='all';
  let paused=false;
  let timer=null;

  function ensureStyles(){
    if(document.getElementById('pool-feed-styles')) return;
    const style=document.createElement('style');
    style.id='pool-feed-styles';
    style.textContent=`
      .pool-feed-card{background:#1b1b1b;border:1px solid #303030;border-radius:10px;padding:16px}
      .pool-feed-controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
      .pool-feed-controls button{background:#202620;border:1px solid #3a4d3d;color:#cfe8d1;padding:7px 10px;border-radius:6px}
      .pool-feed-controls button.active{background:#2b7a3d;border-color:#4da75f;color:white}
      .pool-feed-controls select{background:#111;color:#eee;border:1px solid #444;border-radius:6px;padding:7px 9px}
      .pool-feed-list{display:grid;gap:6px;max-height:520px;overflow:auto}
      .pool-feed-row{display:grid;grid-template-columns:92px 18px minmax(0,1fr);gap:8px;align-items:start;padding:8px 4px;border-bottom:1px solid #272727;font-size:13px}
      .pool-feed-row:last-child{border-bottom:0}
      .pool-feed-time{color:#8b9b8d;font-variant-numeric:tabular-nums;white-space:nowrap}
      .pool-feed-icon{text-align:center}
      .pool-feed-message{word-break:break-word}
      .pool-feed-message code{font-size:11px}
      .feed-success{color:#8ee889}.feed-info{color:#74c0fc}.feed-warning{color:#ffe066}.feed-error{color:#ff8787}
      @media(max-width:560px){.pool-feed-row{grid-template-columns:72px 16px minmax(0,1fr);font-size:12px}}
    `;
    document.head.appendChild(style);
  }

  function iconFor(event){
    if(event.severity==='error') return '●';
    if(event.severity==='warning') return '●';
    if(event.severity==='success') return '●';
    return '●';
  }

  function severityClass(event){
    return 'feed-'+(['success','info','warning','error'].includes(event.severity)?event.severity:'info');
  }

  function shortTime(ts){
    if(!ts) return '—';
    return new Date(Number(ts)*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }

  function escFeed(value){
    return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function render(items){
    const root=document.getElementById('pool-feed-list');
    if(!root) return;
    if(!items.length){root.innerHTML='<div class="muted">No matching pool activity yet.</div>';return;}
    root.innerHTML=items.map(event=>`<div class="pool-feed-row"><div class="pool-feed-time" title="${escFeed(new Date(Number(event.ts||0)*1000).toLocaleString())}">${shortTime(event.ts)}</div><div class="pool-feed-icon ${severityClass(event)}">${iconFor(event)}</div><div class="pool-feed-message">${escFeed(event.message)}</div></div>`).join('');
  }

  async function refresh(){
    if(paused) return;
    const limit=document.getElementById('pool-feed-limit')?.value||'100';
    try{
      const response=await fetch(`/api/admin/events?type=${encodeURIComponent(currentType)}&limit=${encodeURIComponent(limit)}`,{cache:'no-store'});
      const data=await response.json();
      if(!response.ok) throw new Error(data.error||'Pool feed request failed');
      render(Array.isArray(data)?data:[]);
    }catch(error){
      const root=document.getElementById('pool-feed-list');
      if(root) root.innerHTML=`<div class="error">${escFeed(error.message)}</div>`;
    }
  }

  function install(){
    ensureStyles();
    const main=document.querySelector('body main');
    if(!main || document.getElementById('pool-feed-section')) return;
    const section=document.createElement('section');
    section.id='pool-feed-section';
    section.innerHTML=`<div style="display:flex;justify-content:space-between;gap:12px;align-items:end;flex-wrap:wrap"><div><h2 style="margin-bottom:4px">Pool Feed</h2><div class="muted">Recent blocks, payouts, worker activity, treasury actions, and errors.</div></div><span class="muted" style="font-size:12px">Auto-refresh: 10s</span></div><div class="pool-feed-card" style="margin-top:12px"><div class="pool-feed-controls"><button data-feed-type="all" class="active">All</button><button data-feed-type="blocks">Blocks</button><button data-feed-type="payouts">Payouts</button><button data-feed-type="workers">Workers</button><button data-feed-type="treasury">Treasury</button><button data-feed-type="errors">Errors</button><span style="flex:1"></span><label for="pool-feed-limit" style="margin:0">Show</label><select id="pool-feed-limit"><option value="50">50</option><option value="100" selected>100</option></select><button id="pool-feed-pause">Pause auto-refresh</button></div><div id="pool-feed-list" class="pool-feed-list"><div class="muted">Loading pool activity…</div></div></div>`;

    const payoutSection=[...main.querySelectorAll('section')].find(s=>s.querySelector('h2')?.textContent.trim()==='Payout configuration');
    if(payoutSection) payoutSection.insertAdjacentElement('beforebegin',section); else main.appendChild(section);

    section.querySelectorAll('[data-feed-type]').forEach(button=>button.addEventListener('click',()=>{
      currentType=button.dataset.feedType||'all';
      section.querySelectorAll('[data-feed-type]').forEach(x=>x.classList.toggle('active',x===button));
      refresh();
    }));
    document.getElementById('pool-feed-limit')?.addEventListener('change',refresh);
    document.getElementById('pool-feed-pause')?.addEventListener('click',event=>{
      paused=!paused;
      event.currentTarget.textContent=paused?'Resume auto-refresh':'Pause auto-refresh';
      if(!paused) refresh();
    });
    refresh();
    timer=setInterval(refresh,10000);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
