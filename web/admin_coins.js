(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function request(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Request failed');
    return data;
  }
  function formData() {
    return {slug:el('coin-slug').value,name:el('coin-name').value,ticker:el('coin-ticker').value,
      algorithm:el('coin-algorithm').value,pool_address:el('coin-pool-address').value,explorer_url:el('coin-explorer').value,
      logo_url:el('coin-logo').value,theme_color:el('coin-theme').value,
      domain:el('coin-domain').value,stratum_port:el('coin-stratum').value,web_port:el('coin-web').value,
      rpc:{url:el('coin-rpc-url').value,user:el('coin-rpc-user').value,password:el('coin-rpc-password').value},
      payouts:{coinbase_maturity:el('coin-maturity').value,minimum_payout:el('coin-minimum').value,
        pool_fee_percent:el('coin-fee').value,check_interval_seconds:el('coin-payout-interval').value}};
  }
  function render(coins) {
    if (!coins.length) el('coin-list').innerHTML='<p class="muted">No additional coins configured.</p>';
    else el('coin-list').innerHTML='<table><thead><tr><th>Coin</th><th>Website</th><th>Stratum</th><th>Status</th><th></th></tr></thead><tbody>'+coins.map(c=>'<tr><td><strong>'+esc(c.ticker)+'</strong> · '+esc(c.name)+'</td><td><code>'+esc(c.domain)+'</code></td><td><code>:'+esc(c.stratum_port)+'</code></td><td>'+esc(c.status)+'</td><td><button class="secondary coin-plan" data-slug="'+esc(c.slug)+'">Preview</button></td></tr>').join('')+'</tbody></table>';
    document.querySelectorAll('.coin-plan').forEach(button => button.onclick=()=>showPlan(button.dataset.slug));
  }
  async function load() { render((await request('/api/admin/coins')).coins || []); }
  async function showPlan(slug) {
    const plan=await request('/api/admin/coins/'+encodeURIComponent(slug)+'/plan');
    el('coin-plan').innerHTML='<h3>Deployment preview</h3><div class="admin-grid"><div><span class="muted">Install folder</span><code>'+esc(plan.install_dir)+'</code></div><div><span class="muted">Database</span><code>'+esc(plan.database)+'</code></div><div><span class="muted">Services</span><code>'+esc(plan.pool_service)+'<br>'+esc(plan.web_service)+'</code></div><div><span class="muted">Nginx</span><code>'+esc(plan.nginx_site)+'</code></div></div><h4>Readiness checks</h4>'+plan.checks.map(x=>'<div class="'+(x.ok?'notice':'error')+'">'+(x.ok?'✓':'!')+' '+esc(x.name)+' — '+esc(x.detail)+'</div>').join('')+'<h4>Activate '+esc(plan.coin.ticker)+'</h4><div class="form-row"><div><label>Certbot email</label><input id="certbot-email" type="email" placeholder="admin@example.org"></div><button id="prepare-activation">Prepare activation</button></div><div id="activation-result"></div><p class="muted">Activation validates the daemon and DNS, installs isolated services and nginx, then issues and activates a Certbot certificate for this subdomain.</p>';
    el('prepare-activation').onclick=async()=>{const output=el('activation-result');output.textContent='Preparing…';output.className='';try{const result=await request('/api/admin/coins/'+encodeURIComponent(slug)+'/activation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:el('certbot-email').value})});output.innerHTML='<p class="notice">Ready. Run on the pool server:</p><code>'+esc(result.command)+'</code><p class="muted">'+esc(result.note)+'</p>'}catch(error){output.textContent=error.message;output.className='error'}};
  }
  el('save-coin').onclick=async()=>{const message=el('coin-message');message.textContent='Validating and saving draft…';message.className='';try{const coin=await request('/api/admin/coins',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(formData())});message.textContent=coin.ticker+' draft saved.';message.className='notice';await load();await showPlan(coin.slug)}catch(error){message.textContent=error.message;message.className='error'}};
  load().catch(error=>{el('coin-list').innerHTML='<p class="error">'+esc(error.message)+'</p>'});
})();
