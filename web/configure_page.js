(function(){
  const STRATUM='stratum+tcp://pool.yerbas.org:3333';
  const PLACEHOLDER='YOUR_YERB_ADDRESS';

  const commands=[
    {
      name:'cpuminer-opt-gr',
      type:'CPU',
      group:'cpu',
      worker:'cpu',
      command:'cpuminer-opt-gr -a gr -o stratum+tcp://pool.yerbas.org:3333 -u YOUR_YERB_ADDRESS.cpu -p x'
    },
    {
      name:'cpuminer-gr-avx2',
      type:'CPU',
      group:'cpu',
      worker:'avx2',
      command:'cpuminer-gr-avx2 -a gr -o stratum+tcp://pool.yerbas.org:3333 -u YOUR_YERB_ADDRESS.avx2 -p x'
    },
    {
      name:'SRBMiner-MULTI',
      type:'CPU / GPU',
      group:'gpu',
      worker:'srb',
      command:'SRBMiner-MULTI --algorithm ghostrider --pool pool.yerbas.org:3333 --wallet YOUR_YERB_ADDRESS.srb --password x'
    },
    {
      name:'BzMiner',
      type:'GPU',
      group:'gpu',
      worker:'bz',
      command:'bzminer -a ghostrider -w YOUR_YERB_ADDRESS.bz -p stratum+tcp://pool.yerbas.org:3333'
    },
    {
      name:'WildRig Multi',
      type:'GPU',
      group:'gpu',
      worker:'wildrig',
      command:'wildrig.exe --algo ghostrider --url stratum+tcp://pool.yerbas.org:3333 --user YOUR_YERB_ADDRESS.wildrig --pass x'
    }
  ];

  function installNav(){
    const nav=document.querySelector('header nav');
    if(!nav) return;
    nav.innerHTML='<a href="/">Dashboard</a><a href="/miners">Miners</a><a href="/blocks">Blocks</a><a href="/payouts">Payouts</a><a href="/configure">Configure</a>';
  }

  function blockLegacyHomeCommands(){
    if(location.pathname!=='/' || document.getElementById('miner-commands')) return;
    const marker=document.createElement('div');
    marker.id='miner-commands';
    marker.hidden=true;
    marker.setAttribute('aria-hidden','true');
    document.body.appendChild(marker);
  }

  function ensureStyles(){
    if(document.getElementById('configure-page-styles')) return;
    const style=document.createElement('style');
    style.id='configure-page-styles';
    style.textContent=`
      .configure-page{max-width:1200px;margin:0 auto}
      .configure-page .configure-title{margin-bottom:5px}
      .configure-page .quick-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}
      .configure-page .quick-card{padding:15px 17px;border:1px solid var(--yerb-border,#294332);border-radius:9px;background:linear-gradient(155deg,#171d18,#141714)}
      .configure-page .quick-card .label{display:block;color:#91a394;font-size:12px;margin-bottom:5px}
      .configure-page .quick-card strong,.configure-page .quick-card code{font-size:14px;color:#e9f7ea}
      .configure-page .address-card{padding:16px;margin-top:14px;border:1px solid var(--yerb-border,#294332);border-radius:10px;background:linear-gradient(155deg,#171d18,#141714)}
      .configure-page .address-card label{display:block;font-weight:700;margin-bottom:7px}
      .configure-page #configure-address{width:100%;box-sizing:border-box;font-family:monospace;padding:11px 12px;border-radius:7px;border:1px solid rgba(100,255,140,.35);background:#0b120d;color:inherit}
      .configure-page .command-list{display:grid;gap:10px;margin-top:12px}
      .configure-page .command-card{padding:14px;border:1px solid var(--yerb-border,#294332);border-radius:9px;background:linear-gradient(155deg,#171d18,#141714)}
      .configure-page .command-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px;flex-wrap:wrap}
      .configure-page .command-type{font-size:11px;color:#91a394;margin-left:5px;font-weight:500}
      .configure-page .command-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center}
      .configure-page .command-input{width:100%;box-sizing:border-box;font-family:monospace;padding:10px 12px;border-radius:7px;border:1px solid rgba(100,255,140,.25);background:#0b120d;color:inherit}
      .configure-page .copy-command,.configure-page .copy-stratum{cursor:pointer;background:#1d2a20;color:#b9e6bb;border:1px solid #35553d;border-radius:6px;padding:8px 11px;font-weight:700}
      .configure-page .copy-command:hover,.configure-page .copy-stratum:hover{border-color:var(--yerb,#65c466);color:#e9f7ea}
      .configure-page .section-copy{margin-top:32px}
      @media(max-width:700px){
        .configure-page .quick-grid{grid-template-columns:1fr}
        .configure-page .command-row{grid-template-columns:1fr}
        .configure-page .copy-command{width:100%}
      }
    `;
    document.head.appendChild(style);
  }

  function validAddress(value){
    return /^y[1-9A-HJ-NP-Za-km-z]{25,40}$/.test(value);
  }

  function copyText(text,button){
    const done=()=>{
      const old=button.textContent;
      button.textContent='Copied!';
      button.disabled=true;
      setTimeout(()=>{button.textContent=old;button.disabled=false;},1200);
    };
    if(navigator.clipboard && window.isSecureContext){
      navigator.clipboard.writeText(text).then(done).catch(()=>fallbackCopy(text,done));
    }else fallbackCopy(text,done);
  }

  function fallbackCopy(text,done){
    const area=document.createElement('textarea');
    area.value=text;
    area.setAttribute('readonly','');
    area.style.cssText='position:fixed;opacity:0;pointer-events:none';
    document.body.appendChild(area);
    area.select();
    try{document.execCommand('copy');done();}catch(e){}
    area.remove();
  }

  function commandCards(group){
    return commands.filter(c=>c.group===group).map(c=>`
      <div class="command-card">
        <div class="command-head">
          <div><strong>${esc(c.name)}</strong><span class="command-type">${esc(c.type)}</span></div>
        </div>
        <div class="command-row">
          <input class="command-input" data-template="${esc(c.command)}" type="text" readonly value="${esc(c.command)}" aria-label="${esc(c.name)} command">
          <button type="button" class="copy-command">Copy</button>
        </div>
      </div>`).join('');
  }

  function renderConfigure(){
    if(location.pathname!=='/configure') return;
    const root=document.querySelector('main#app');
    if(!root) return;
    ensureStyles();
    root.innerHTML=`
      <div class="configure-page">
        <section>
          <h2 class="configure-title">Configure</h2>
          <div class="muted">Enter your Yerbas payout address once and copy a ready-to-run mining command for your hardware.</div>
          <div class="quick-grid">
            <div class="quick-card"><span class="label">Stratum endpoint</span><code>${STRATUM}</code> <button type="button" class="copy-stratum">Copy</button></div>
            <div class="quick-card"><span class="label">Algorithm</span><strong>GhostRider</strong></div>
          </div>
          <div class="address-card">
            <label for="configure-address">Yerbas payout address</label>
            <input id="configure-address" type="text" autocomplete="off" spellcheck="false" placeholder="Enter your YERB address">
            <div id="configure-address-message" class="small muted" style="margin-top:7px">Commands update automatically as you type. Worker names after the dot can be changed.</div>
          </div>
        </section>

        <section class="section-copy">
          <h2>Prebuilt Miner Commands</h2>
          <div class="muted">Password is <code>x</code>. The worker suffix is optional and can be renamed for each rig.</div>
        </section>

        <section>
          <h2>CPU Miners</h2>
          <div class="command-list">${commandCards('cpu')}</div>
        </section>

        <section>
          <h2>GPU Miners</h2>
          <div class="command-list">${commandCards('gpu')}</div>
        </section>
      </div>`;

    const addressInput=root.querySelector('#configure-address');
    const message=root.querySelector('#configure-address-message');
    const commandInputs=[...root.querySelectorAll('.command-input')];

    const updateCommands=()=>{
      const address=(addressInput.value||'').trim();
      const valid=!address || validAddress(address);
      addressInput.style.borderColor=valid?'rgba(100,255,140,.35)':'#a84a4a';
      message.textContent=!address
        ?'Commands update automatically as you type. Worker names after the dot can be changed.'
        :valid
          ?'Commands are ready with your Yerbas payout address.'
          :'This does not look like a valid Yerbas payout address yet.';
      message.style.color=valid?'':'#ffaaaa';
      commandInputs.forEach(input=>{
        input.value=(input.dataset.template||'').replaceAll(PLACEHOLDER,address||PLACEHOLDER);
      });
    };

    addressInput.addEventListener('input',updateCommands);
    addressInput.addEventListener('paste',()=>setTimeout(updateCommands,0));
    commandInputs.forEach(input=>input.addEventListener('click',()=>input.select()));
    root.querySelectorAll('.copy-command').forEach(button=>{
      button.addEventListener('click',()=>{
        const input=button.closest('.command-card')?.querySelector('.command-input');
        if(input) copyText(input.value,button);
      });
    });
    root.querySelector('.copy-stratum')?.addEventListener('click',event=>copyText(STRATUM,event.currentTarget));
    addressInput.focus();
  }

  function install(){
    installNav();
    blockLegacyHomeCommands();
    renderConfigure();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
