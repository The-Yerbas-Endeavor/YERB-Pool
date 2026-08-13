(function(){
  const REQUIRED_CONFIRMATIONS = 100;
  let rewardSummaryBusy = false;
  let workerRejectBusy = false;
  let accountRejectBusy = false;

  function friendlyLedgerType(type) {
    const labels = {
      block_immature: 'Pending Reward',
      block_mature: 'Mature Reward',
      block_orphan: 'Orphaned Reward',
      payout: 'Payout'
    };
    return labels[type] || type || '';
  }

  function friendlyRejectReason(reason) {
    const value=String(reason||'').trim();
    if(!value) return 'Legacy / unspecified';
    const labels={
      'duplicate share':'Duplicate share',
      'low difficulty share':'Low difficulty',
      'stale job':'Stale job',
      'worker mismatch':'Worker mismatch',
      'invalid mining.submit':'Invalid submission',
      'ntime below mintime':'Invalid timestamp'
    };
    return labels[value] || value;
  }

  function removeShareSummaryCards() {
    if(location.pathname!=='/') return;
    document.querySelectorAll('main#app .card').forEach(card=>{
      const label=card.querySelector('.muted')?.textContent?.trim();
      if(label==='Accepted Shares' || label==='Rejected Shares') card.remove();
    });
  }

  function rejectBreakdown(items) {
    const counts=new Map();
    for(const item of items||[]){
      const key=friendlyRejectReason(item.rejection_reason);
      counts.set(key,(counts.get(key)||0)+1);
    }
    const sorted=[...counts.entries()].sort((a,b)=>b[1]-a[1]);
    if(!sorted.length) return '<div class="empty">No recorded rejected shares yet.</div>';
    const total=sorted.reduce((n,x)=>n+x[1],0);
    return `<div class="metric-strip">${sorted.map(([reason,count])=>`<div class="metric"><span class="muted small">${esc(reason)}</span><strong>${count.toLocaleString()}</strong><span class="small muted">${(count/total*100).toFixed(1)}% of recorded rejects</span></div>`).join('')}</div>`;
  }

  window.renderBlocks = function(b){
    if(!b.length) return '<div class="empty">No blocks found yet.</div>';
    return table(
      ['Height','Status','Confirmations','Network Reward','Pool Reward','Hash'],
      b.map(x=>{
        const c=Number(x.confirmations||0);
        const label=x.status==='orphan'?'Orphan':c>=REQUIRED_CONFIRMATIONS?'Confirmed':'Pending';
        return `<tr><td>${x.height??'—'}</td><td>${status(label)}</td><td>${c} / ${REQUIRED_CONFIRMATIONS}</td><td>${coin(x.network_reward_atomic||8000000000)} YERB</td><td>${coin(x.reward_atomic)} YERB</td><td>${explorerBlock(x.block_hash)}</td></tr>`;
      })
    );
  };

  window.renderMiners = function(m){
    if(!m.length) return '<div class="empty">No miners yet.</div>';
    return table(
      ['Address','Workers','Accepted','Rejected','Mature Balance','Immature Balance','Total Paid'],
      m.map(x=>`<tr><td>${addressLink(x.address)}<div class="small">${explorerAddress(x.address)}</div></td><td><a href="/workers?address=${encodeURIComponent(x.address)}">${x.worker_count}</a></td><td>${x.accepted_shares||0}</td><td>${x.rejected_shares||0}</td><td>${coin(x.balance_atomic)} YERB</td><td>${coin(x.immature_balance_atomic)} YERB</td><td>${coin(x.total_paid_atomic)} YERB</td></tr>`)
    );
  };

  async function ensureRewardSummary(){
    if(location.pathname!=='/' || rewardSummaryBusy || document.getElementById('reward-summary')) return;
    const main=document.querySelector('main#app');
    if(!main) return;
    rewardSummaryBusy=true;
    try{
      const [blocks,summary]=await Promise.all([
        get('/api/blocks?limit=10').catch(()=>[]),
        get('/api/summary').catch(()=>null)
      ]);
      if(!summary || location.pathname!=='/' || document.getElementById('reward-summary')) return;
      const panel=document.createElement('section');
      panel.id='reward-summary';
      const first=main.querySelector('.grid');
      if(first) first.insertAdjacentElement('afterend',panel); else main.prepend(panel);
      const network=blocks.length?Number(blocks[0].network_reward_atomic||8000000000):8000000000;
      const pool=blocks.length?Number(blocks[0].reward_atomic||0):0;
      panel.innerHTML=`<div class="section-head"><div><h2 style="margin-bottom:4px">Reward & Maturity</h2><div class="muted">Network reward includes required Yerbas coinbase payments; pool reward is the portion distributed to miners.</div></div><a href="/blocks">Blocks →</a></div><div class="metric-strip"><div class="metric"><span class="muted small">Network Block Reward</span><strong>${coin(network)} YERB</strong></div><div class="metric"><span class="muted small">Pool / Miner Reward</span><strong>${coin(pool)} YERB</strong></div><div class="metric"><span class="muted small">Coinbase Maturity</span><strong>${REQUIRED_CONFIRMATIONS} blocks</strong></div><div class="metric"><span class="muted small">Pending Miner Rewards</span><strong>${coin(summary.accounts.immature_atomic)} YERB</strong></div></div>`;
    } finally {
      rewardSummaryBusy=false;
    }
  }

  async function ensureWorkerRejectBreakdown(){
    if(!location.pathname.startsWith('/worker/') || workerRejectBusy || document.getElementById('worker-reject-breakdown')) return;
    const main=document.querySelector('main#app');
    if(!main) return;
    workerRejectBusy=true;
    try{
      const id=location.pathname.slice('/worker/'.length);
      const info=await get('/api/worker/'+encodeURIComponent(id)+'/stats?hours=24&bucket=300').catch(()=>null);
      if(!info) return;
      const all=await get('/api/shares?status=rejected&limit=1000').catch(()=>[]);
      const login=info.address+'.'+info.name;
      const rejected=all.filter(x=>x.worker===login);
      if(document.getElementById('worker-reject-breakdown')) return;
      const section=document.createElement('section');
      section.id='worker-reject-breakdown';
      section.innerHTML=`<div class="section-head"><div><h2 style="margin-bottom:4px">Reject Breakdown</h2><div class="muted">Recent recorded Stratum rejects for this worker. Rejected work never receives payout credit.</div></div><a href="/shares?status=rejected">Rejected shares →</a></div>${rejectBreakdown(rejected)}`;
      main.appendChild(section);
    } finally {
      workerRejectBusy=false;
    }
  }

  async function ensureAccountRejectBreakdown(){
    if(!location.pathname.startsWith('/account/') || accountRejectBusy || document.getElementById('account-reject-breakdown')) return;
    const main=document.querySelector('main#app');
    if(!main) return;
    accountRejectBusy=true;
    try{
      const address=decodeURIComponent(location.pathname.slice('/account/'.length));
      const rejected=await get('/api/shares?status=rejected&address='+encodeURIComponent(address)+'&limit=1000').catch(()=>[]);
      if(document.getElementById('account-reject-breakdown')) return;
      const section=document.createElement('section');
      section.id='account-reject-breakdown';
      section.innerHTML=`<div class="section-head"><div><h2 style="margin-bottom:4px">Reject Breakdown</h2><div class="muted">Recent recorded Stratum rejects for all workers on this payout address.</div></div><a href="/shares?status=rejected&address=${encodeURIComponent(address)}">Rejected shares →</a></div>${rejectBreakdown(rejected)}`;
      const workersHeading=[...main.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Workers');
      const workersSection=workersHeading?.closest('section');
      if(workersSection) workersSection.insertAdjacentElement('afterend',section); else main.appendChild(section);
    } finally {
      accountRejectBusy=false;
    }
  }

  const originalDashboard = window.dashboard;
  window.dashboard = async function(){
    await originalDashboard();
    removeShareSummaryCards();
    await ensureRewardSummary();
  };

  const originalAccount = window.account;
  window.account = async function(){
    await originalAccount();
    const a=decodeURIComponent(location.pathname.slice('/account/'.length));
    if(!a) return;
    const x=await get('/api/account/'+encodeURIComponent(a)).catch(()=>null);
    if(!x) return;

    document.querySelectorAll('.card .muted').forEach(el=>{
      if(el.textContent.trim()==='Balance') el.textContent='Mature Balance';
      if(el.textContent.trim()==='Immature' || el.textContent.trim()==='Immature Balance') el.textContent='Immature Balance';
    });

    const ledgerHeading=[...document.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Ledger');
    if(ledgerHeading){
      const section=ledgerHeading.closest('section');
      const ledger=x.ledger||[];
      const blockMap=new Map();
      const blocks=await get('/api/blocks?limit=500').catch(()=>[]);
      for(const b of blocks) blockMap.set(Number(b.id),b);
      const body=ledger.length?table(['Time','Type','Amount','Block','Note'],ledger.map(l=>{
        const b=blockMap.get(Number(l.block_id));
        let note=l.note||'';
        if(l.entry_type==='block_immature'){
          const network=b?coin(b.network_reward_atomic||8000000000):'80.00';
          const pool=b?coin(b.reward_atomic):coin(l.amount_atomic);
          note=`Miner share of ${pool} YERB pool reward; ${network} YERB network reward. Matures after ${REQUIRED_CONFIRMATIONS} confirmations.`;
        } else if(l.entry_type==='block_mature') {
          note='Reward reached 100 confirmations and moved to mature balance.';
        } else if(l.entry_type==='block_orphan') {
          note='Previously pending reward removed because the block was orphaned.';
        }
        return `<tr><td>${when(l.ts)}</td><td>${status(friendlyLedgerType(l.entry_type))}</td><td>${coin(l.amount_atomic)} YERB</td><td>${l.block_id??'—'}</td><td>${esc(note)}</td></tr>`;
      })):'<div class="empty">No ledger entries.</div>';
      if(section) section.innerHTML='<h2>Ledger</h2>'+body;
    }
    await ensureAccountRejectBreakdown();
  };

  window.shares = async function(){
    const q=new URLSearchParams(location.search),statusQ=q.get('status'),address=q.get('address'),params=new URLSearchParams({limit:'1000'});
    if(statusQ)params.set('status',statusQ);
    if(address)params.set('address',address);
    const s=await get('/api/shares?'+params);
    const headers=['Time','Address / Worker','Difficulty','Result'];
    if(statusQ==='rejected' || s.some(x=>x.rejection_reason)) headers.push('Reason');
    headers.push('Block Candidate','Hash');
    const rows=s.map(x=>{
      const cells=[
        `<td>${when(x.ts)}</td>`,
        `<td>${x.address?addressLink(x.address):''}<div><code>${esc(x.worker)}</code></div></td>`,
        `<td>${Number(x.difficulty).toExponential(4)}</td>`,
        `<td>${x.accepted?'<span class="ok">Accepted</span>':'<span class="bad">Rejected</span>'}</td>`
      ];
      if(statusQ==='rejected' || s.some(y=>y.rejection_reason)) cells.push(`<td>${x.accepted?'—':esc(friendlyRejectReason(x.rejection_reason))}</td>`);
      cells.push(`<td>${x.block_candidate?'Yes':'No'}</td>`,`<td><code>${esc(short(x.hash))}</code></td>`);
      return '<tr>'+cells.join('')+'</tr>';
    });
    app.innerHTML=`<section><h2>${statusQ?statusQ[0].toUpperCase()+statusQ.slice(1)+' ':''}Shares</h2>${address?`<div class="muted">Address: ${addressLink(address)}</div>`:''}${s.length?table(headers,rows):'<div class="empty">No shares recorded.</div>'}</section>`;
  };

  // The original index.html installs refresh timers before this script loads,
  // so those timers retain references to the original render functions. Watch
  // the app root and immediately re-apply persistent enhancements after every
  // redraw. This prevents the removed share cards from reappearing at 10s.
  const appRoot=document.querySelector('main#app');
  if(appRoot){
    const observer=new MutationObserver(()=>{
      if(location.pathname==='/'){
        removeShareSummaryCards();
        ensureRewardSummary();
      } else if(location.pathname.startsWith('/worker/')) {
        ensureWorkerRejectBreakdown();
      } else if(location.pathname.startsWith('/account/')) {
        ensureAccountRejectBreakdown();
      }
    });
    observer.observe(appRoot,{childList:true,subtree:true});
  }

  if(location.pathname==='/') window.dashboard();
  else if(location.pathname==='/miners') window.miners();
  else if(location.pathname==='/blocks' || location.pathname==='/blocks/pending') window.blocks();
  else if(location.pathname==='/shares') window.shares();
  else if(location.pathname.startsWith('/account/')) window.account();
  else if(location.pathname.startsWith('/worker/')) ensureWorkerRejectBreakdown();
})();
