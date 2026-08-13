(function(){
  const REQUIRED_CONFIRMATIONS = 100;

  function friendlyLedgerType(type) {
    const labels = {
      block_immature: 'Pending Reward',
      block_mature: 'Mature Reward',
      block_orphan: 'Orphaned Reward',
      payout: 'Payout'
    };
    return labels[type] || type || '';
  }

  // Keep the accounting values untouched; only clarify what each number means.
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

  const originalDashboard = window.dashboard;
  window.dashboard = async function(){
    await originalDashboard();
    const blocks = await get('/api/blocks?limit=10').catch(()=>[]);
    const summary = await get('/api/summary').catch(()=>null);
    const main=document.querySelector('main#app');
    if(!main || !summary) return;

    let panel=document.getElementById('reward-summary');
    if(!panel){
      panel=document.createElement('section');
      panel.id='reward-summary';
      const first=main.querySelector('.grid');
      if(first) first.insertAdjacentElement('afterend',panel); else main.prepend(panel);
    }
    const network=blocks.length?Number(blocks[0].network_reward_atomic||8000000000):8000000000;
    const pool=blocks.length?Number(blocks[0].reward_atomic||0):0;
    panel.innerHTML=`<div class="section-head"><div><h2 style="margin-bottom:4px">Reward & Maturity</h2><div class="muted">Network reward includes required Yerbas coinbase payments; pool reward is the portion distributed to miners.</div></div><a href="/blocks">Blocks →</a></div><div class="metric-strip"><div class="metric"><span class="muted small">Network Block Reward</span><strong>${coin(network)} YERB</strong></div><div class="metric"><span class="muted small">Pool / Miner Reward</span><strong>${coin(pool)} YERB</strong></div><div class="metric"><span class="muted small">Coinbase Maturity</span><strong>${REQUIRED_CONFIRMATIONS} blocks</strong></div><div class="metric"><span class="muted small">Pending Miner Rewards</span><strong>${coin(summary.accounts.immature_atomic)} YERB</strong></div></div>`;
  };

  const originalAccount = window.account;
  window.account = async function(){
    await originalAccount();
    const a=decodeURIComponent(location.pathname.slice('/account/'.length));
    if(!a) return;
    const x=await get('/api/account/'+encodeURIComponent(a)).catch(()=>null);
    if(!x) return;

    // Relabel account summary cards.
    document.querySelectorAll('.card .muted').forEach(el=>{
      if(el.textContent.trim()==='Balance') el.textContent='Mature Balance';
      if(el.textContent.trim()==='Immature' || el.textContent.trim()==='Immature Balance') el.textContent='Immature Balance';
    });

    // Replace internal ledger terms and generic notes with clear miner-facing language.
    const ledgerHeading=[...document.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Ledger');
    if(!ledgerHeading) return;
    const section=ledgerHeading.closest('section');
    if(!section) return;
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
    section.innerHTML='<h2>Ledger</h2>'+body;
  };

  // Re-render the current route once so the clearer labels apply immediately.
  if(location.pathname==='/') window.dashboard();
  else if(location.pathname==='/miners') window.miners();
  else if(location.pathname==='/blocks' || location.pathname==='/blocks/pending') window.blocks();
  else if(location.pathname.startsWith('/account/')) window.account();
})();
