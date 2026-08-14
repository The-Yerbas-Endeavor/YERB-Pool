(function(){
  function validAddress(value){
    return /^y[1-9A-HJ-NP-Za-km-z]{25,40}$/.test(value);
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

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',installAddressSearch);
  else installAddressSearch();
})();
