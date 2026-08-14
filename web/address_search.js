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

  function installBrandLogo(){
    const brand=document.querySelector('.brand>div:first-child');
    if(!brand || brand.querySelector('.yerbas-header-logo')) return;

    if(!document.getElementById('yerbas-header-logo-style')){
      const style=document.createElement('style');
      style.id='yerbas-header-logo-style';
      style.textContent=`
        .brand>div:first-child:before{display:none!important;content:none!important}
        .brand>div:first-child{position:relative!important;padding-left:66px!important}
        .yerbas-header-logo{
          position:absolute;
          left:0;
          top:-4px;
          width:54px;
          height:54px;
          object-fit:contain;
          display:block;
          filter:drop-shadow(0 7px 12px rgba(0,0,0,.28));
        }
        @media(max-width:700px){
          .brand>div:first-child{padding-left:56px!important}
          .yerbas-header-logo{width:46px;height:46px;top:-2px}
        }
      `;
      document.head.appendChild(style);
    }

    const logo=document.createElement('img');
    logo.className='yerbas-header-logo';
    logo.src='/yerbas-logo.svg';
    logo.alt='Yerbas';
    logo.width=54;
    logo.height=54;
    brand.prepend(logo);
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

  function installLedgerTypeStyles(){
    if(document.getElementById('yerb-ledger-type-styles')) return;
    const style=document.createElement('style');
    style.id='yerb-ledger-type-styles';
    style.textContent=`
      .ledger-type-badge{font-weight:700;border-width:1px!important}
      .ledger-type-pending{color:#ffe066!important;background:rgba(255,224,102,.13)!important;border-color:rgba(255,224,102,.38)!important}
      .ledger-type-mature{color:#8ee889!important;background:rgba(101,196,102,.14)!important;border-color:rgba(101,196,102,.40)!important}
      .ledger-type-payout{color:#74c0fc!important;background:rgba(77,171,247,.14)!important;border-color:rgba(77,171,247,.40)!important}
      .ledger-type-fee{color:#ffad66!important;background:rgba(255,159,67,.14)!important;border-color:rgba(255,159,67,.40)!important}
      .ledger-type-reward{color:#ffd166!important;background:rgba(255,209,102,.14)!important;border-color:rgba(255,209,102,.40)!important}
      .ledger-type-debit{color:#ff8787!important;background:rgba(255,107,107,.14)!important;border-color:rgba(255,107,107,.40)!important}
      .ledger-type-orphan{color:#adb5bd!important;background:rgba(173,181,189,.12)!important;border-color:rgba(173,181,189,.32)!important}
    `;
    document.head.appendChild(style);
  }

  function colorLedgerTypes(){
    if(!location.pathname.startsWith('/account/')) return;
    const main=document.querySelector('main#app');
    if(!main) return;
    const heading=[...main.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Ledger');
    const section=heading?.closest('section');
    if(!section) return;

    installLedgerTypeStyles();
    section.querySelectorAll('tbody tr').forEach(row=>{
      const badge=row.querySelector('td:nth-child(2) .badge');
      if(!badge) return;
      const label=badge.textContent.trim().toLowerCase();
      badge.classList.add('ledger-type-badge');
      badge.classList.remove(
        'ledger-type-pending','ledger-type-mature','ledger-type-payout',
        'ledger-type-fee','ledger-type-reward','ledger-type-debit','ledger-type-orphan'
      );
      if(label.includes('orphan')) badge.classList.add('ledger-type-orphan');
      else if(label.includes('pending') || label.includes('immature')) badge.classList.add('ledger-type-pending');
      else if(label.includes('mature') || label.includes('credit')) badge.classList.add('ledger-type-mature');
      else if(label.includes('payout')) badge.classList.add('ledger-type-payout');
      else if(label.includes('fee')) badge.classList.add('ledger-type-fee');
      else if(label.includes('reward')) badge.classList.add('ledger-type-reward');
      else if(label.includes('debit')) badge.classList.add('ledger-type-debit');
    });
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
    installBrandLogo();
    installAddressSearch();
    installHeaderConnect();
    groupHomePanels();
    colorLedgerTypes();

    const main=document.querySelector('main#app');
    if(main && location.pathname==='/'){
      const observer=new MutationObserver(groupHomePanels);
      observer.observe(main,{childList:true,subtree:true});
      requestAnimationFrame(groupHomePanels);
    }
    if(main && location.pathname.startsWith('/account/')){
      const observer=new MutationObserver(colorLedgerTypes);
      observer.observe(main,{childList:true,subtree:true});
      requestAnimationFrame(colorLedgerTypes);
    }
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
