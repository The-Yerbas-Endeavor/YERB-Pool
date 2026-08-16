(function(){
  const root=document.getElementById('admin-users');
  if(!root) return;

  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const atomic=v=>(Number(v||0)/1e8).toFixed(2)+' YERB';
  const when=t=>t?new Date(Number(t)*1000).toLocaleString():'—';
  const ago=t=>{if(!t)return'never';const d=Math.max(0,Math.floor(Date.now()/1000-Number(t)));if(d<60)return d+'s ago';if(d<3600)return Math.floor(d/60)+'m ago';if(d<86400)return Math.floor(d/3600)+'h ago';return Math.floor(d/86400)+'d ago'};
  const hashRate=v=>{v=Number(v||0);if(v>=1e9)return(v/1e9).toFixed(2)+' GH/s';if(v>=1e6)return(v/1e6).toFixed(2)+' MH/s';if(v>=1e3)return(v/1e3).toFixed(2)+' kH/s';return v.toFixed(1)+' H/s'};

  async function api(url,body){
    const opt=body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
    const r=await fetch(url,opt),x=await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(x.error||r.statusText);
    return x;
  }

  function ipList(user){
    if(!user.ips?.length) return '<span class="muted">Not recorded yet</span>';
    return user.ips.map(ip=>`<div class="admin-ip"><code>${esc(ip.ip_address)}</code> ${ip.banned?'<span class="user-badge user-banned">Banned</span>':''}<button class="user-mini-btn ${ip.banned?'':'danger'}" data-ip="${esc(ip.ip_address)}" data-ban="${ip.banned?'0':'1'}">${ip.banned?'Unban':'Ban IP'}</button><div class="muted user-small">Last seen ${ago(ip.last_seen_at)} · ${Number(ip.connection_count||0).toLocaleString()} connection${Number(ip.connection_count||0)===1?'':'s'}</div></div>`).join('');
  }

  function render(users){
    if(!users.length){root.innerHTML='<div class="admin-card muted">No miner users have been recorded yet.</div>';return;}
    root.innerHTML=`<div class="user-toolbar"><input id="admin-user-search" type="search" placeholder="Search address, worker or IP"><span class="muted">${users.length.toLocaleString()} user${users.length===1?'':'s'}</span></div><div class="admin-user-table-wrap"><table class="admin-user-table"><thead><tr><th>User</th><th>Balances</th><th>Hashrate / Workers</th><th>IP addresses</th><th>Activity</th><th>Controls</th></tr></thead><tbody>${users.map(u=>`<tr data-user-row data-search="${esc([u.address,(u.worker_names||[]).join(' '),(u.ips||[]).map(x=>x.ip_address).join(' ')].join(' ').toLowerCase())}"><td><a href="/account/${encodeURIComponent(u.address)}" target="_blank"><code>${esc(u.address)}</code></a><div class="muted user-small">Created ${when(u.created_at)}</div><div class="muted user-small">Earned ${atomic(u.total_earned_atomic)} · Paid ${atomic(u.total_paid_atomic)}</div></td><td><strong>${atomic(u.balance_atomic)}</strong><div class="muted user-small">Immature ${atomic(u.immature_balance_atomic)}</div><div class="muted user-small">Min payout ${u.minimum_payout_atomic?atomic(u.minimum_payout_atomic):'Pool default'}</div></td><td><strong>${hashRate(u.hashrate)}</strong><div class="muted user-small">${Number(u.active_workers||0)} active / ${Number(u.worker_count||0)} total</div>${u.worker_names?.length?`<div class="muted user-small">${u.worker_names.map(esc).join(', ')}</div>`:''}</td><td>${ipList(u)}</td><td>Last share ${ago(u.last_share_at)}<div class="muted user-small">Last worker seen ${ago(u.last_seen_at)}</div><div class="muted user-small">Accepted ${Number(u.accepted_shares||0).toLocaleString()} · Rejected ${Number(u.rejected_shares||0).toLocaleString()}</div></td><td>${u.enabled?'<span class="user-badge user-ok">Payments active</span>':'<span class="user-badge user-paused">Payments paused</span>'}<div style="margin-top:8px"><button class="user-control-btn ${u.enabled?'danger':''}" data-address="${esc(u.address)}" data-enabled="${u.enabled?'0':'1'}">${u.enabled?'Pause payments':'Resume payments'}</button></div></td></tr>`).join('')}</tbody></table></div><div id="admin-user-message"></div>`;

    const search=root.querySelector('#admin-user-search');
    search?.addEventListener('input',()=>{const q=search.value.trim().toLowerCase();root.querySelectorAll('[data-user-row]').forEach(row=>row.hidden=!!q&&!row.dataset.search.includes(q));});

    root.querySelectorAll('[data-address]').forEach(btn=>btn.addEventListener('click',async()=>{
      const enable=btn.dataset.enabled==='1',address=btn.dataset.address;
      if(!enable && !confirm(`Pause automated payouts for ${address}? The balance will remain credited and can be resumed later.`)) return;
      btn.disabled=true;
      try{await api('/api/admin/users/payment',{address,enabled:enable});await load();}catch(e){alert(e.message);btn.disabled=false;}
    }));

    root.querySelectorAll('[data-ip]').forEach(btn=>btn.addEventListener('click',async()=>{
      const ban=btn.dataset.ban==='1',ip=btn.dataset.ip;
      if(ban && !confirm(`Ban ${ip} from connecting to the Stratum pool? This can affect every miner sharing that public IP.`)) return;
      btn.disabled=true;
      try{await api('/api/admin/users/ip-ban',{ip_address:ip,banned:ban});await load();}catch(e){alert(e.message);btn.disabled=false;}
    }));
  }

  async function load(){
    root.innerHTML='<div class="admin-card">Loading users…</div>';
    try{const x=await api('/api/admin/users');render(x.users||[]);}catch(e){root.innerHTML=`<div class="admin-card error">${esc(e.message)}</div>`;}
  }
  window.loadAdminUsers=load;
  load();
})();
