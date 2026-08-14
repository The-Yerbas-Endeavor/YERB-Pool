(function(){
  const STRATUM_URL='stratum+tcp://pool.yerbas.org:3333';

  function validAddress(value){
    return /^y[1-9A-HJ-NP-Za-km-z]{25,40}$/.test(value);
  }

  function copyStratum(button){
    const done=()=>{
      const old=button.textContent;
      button.textContent='Copied!';
      button.disabled=true;
      setTimeout(()=>{button.textContent=old;button.disabled=false;},1200);
    };
    if(navigator.clipboard && window.isSecureContext){
      navigator.clipboard.writeText(STRATUM_URL).then(done).catch(()=>fallbackCopy(done));
    }else{
      fallbackCopy(done);
    }
  }

  function fallbackCopy(done){
    const area=document.createElement('textarea');
    area.value=STRATUM_URL;
    area.setAttribute('readonly','');
    area.style.cssText='position:fixed;opacity:0;pointer-events:none';
    document.body.appendChild(area);
    area.select();
    try{document.execCommand('copy');done();}catch(e){}
    area.remove();
  }

  function installHeaderConnect(){
    if(document.getElementById('yerb-header-connect')) return;
    const header=document.querySelector('header .head');
    if(!header) return;

    const row=document.createElement('div');
    row.id='yerb-header-connect';
    row.innerHTML=`<span>Connect:</span> <code title="Click to select">${STRATUM_URL}</code> <button type="button">Copy</button>`;
    const code=row.querySelector('code');
    const button=row.querySelector('button');
    code.addEventListener('click',()=>{
      const range=document.createRange();
      range.selectNodeContents(code);
      const selection=window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    });
    button.addEventListener('click',()=>copyStratum(button));
    header.appendChild(row);
  }

  function installAddressSearch(){
    if(document.getElementById('yerb-address-search')) return;
    const header=document.querySelector('header .head');
    if(!header) return;

    const form=document.createElement('form');
    form.id='yerb-address-search';
    form.setAttribute('role','search');
    form.style.cssText='display:flex;gap:7px;align-items:center;margin-top:14px;max-width:620px;width:100%';
    form.innerHTML=`
      <input id="yerb-address-query" type="search" inputmode="text" autocomplete="off" spellcheck="false"
        aria-label="Search YERB miner address" placeholder="Search your YERB payout address"
        style="flex:1;min-width:180px;background:#111;color:#eee;border:1px solid #3a3a3a;border-radius:7px;padding:9px 11px;font-family:monospace">
      <button type="submit"
        style="background:#2b7a3d;color:#fff;border:0;border-radius:7px;padding:9px 14px;font-weight:700;cursor:pointer">Search</button>`;

    const message=document.createElement('div');
    message.id='yerb-address-search-message';
    message.style.cssText='font-size:12px;margin-top:5px;min-height:16px;color:#aaa';

    const wrap=document.createElement('div');
    wrap.style.cssText='width:100%';
    wrap.appendChild(form);
    wrap.appendChild(message);
    header.appendChild(wrap);

    form.addEventListener('submit',async event=>{
      event.preventDefault();
      const input=document.getElementById('yerb-address-query');
      const address=(input.value||'').trim();
      message.style.color='#aaa';

      if(!validAddress(address)){
        message.style.color='#ffaaaa';
        message.textContent='Enter a valid YERB address.';
        input.focus();
        return;
      }

      message.textContent='Looking up miner account…';
      try{
        const response=await fetch('/api/account/'+encodeURIComponent(address),{cache:'no-store'});
        if(response.ok){
          location.href='/account/'+encodeURIComponent(address);
          return;
        }
        if(response.status===404){
          message.style.color='#ffcf8a';
          message.textContent='No mining account found for that address yet.';
          return;
        }
        const data=await response.json().catch(()=>({}));
        throw new Error(data.error||'Address lookup failed');
      }catch(error){
        message.style.color='#ffaaaa';
        message.textContent=error.message||'Address lookup failed';
      }
    });

    if(location.pathname.startsWith('/account/')){
      try{
        document.getElementById('yerb-address-query').value=decodeURIComponent(location.pathname.slice('/account/'.length));
      }catch(e){}
    }
  }

  function groupHomePanels(){
    if(location.pathname!=='/') return;
    const main=document.querySelector('main#app');
    if(!main) return;

    const findSection=label=>[...main.querySelectorAll('h2')]
      .find(h=>h.textContent.trim()===label)?.closest('section');
    const workers=findSection('Top Workers');
    const blocks=findSection('Recent Blocks');
    const miners=findSection('Miners');
    if(!workers || !blocks || !miners) return;

    let row=document.getElementById('home-panel-row');
    if(!row){
      row=document.createElement('div');
      row.id='home-panel-row';
      workers.parentNode.insertBefore(row,workers);
    }
    if(workers.parentNode!==row) row.appendChild(workers);
    if(blocks.parentNode!==row) row.appendChild(blocks);
    if(miners.parentNode!==row) row.appendChild(miners);
  }

  function install(){
    installAddressSearch();
    installHeaderConnect();
    groupHomePanels();

    if(location.pathname==='/'){
      const main=document.querySelector('main#app');
      if(main){
        const observer=new MutationObserver(groupHomePanels);
        observer.observe(main,{childList:true,subtree:true});
        requestAnimationFrame(groupHomePanels);
      }
    }
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
