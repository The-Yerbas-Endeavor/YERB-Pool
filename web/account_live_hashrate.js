(function(){
  // Stable global hook for the miner-address search UI.
  if(!document.querySelector('script[data-yerb-address-search]')){
    const script=document.createElement('script');
    script.src='/address_search.js?v=1';
    script.async=true;
    script.dataset.yerbAddressSearch='1';
    document.head.appendChild(script);
  }

  if(!location.pathname.startsWith('/account/')) return;

  const address=decodeURIComponent(location.pathname.slice('/account/'.length));
  if(!address) return;

  function fmtHash(v){
    v=Number(v||0);
    if(v>=1e9) return (v/1e9).toFixed(2)+' GH/s';
    if(v>=1e6) return (v/1e6).toFixed(2)+' MH/s';
    if(v>=1e3) return (v/1e3).toFixed(2)+' kH/s';
    return v.toFixed(1)+' H/s';
  }

  function updateCard(value, windowSeconds){
    const cards=[...document.querySelectorAll('main#app .card')];
    const card=cards.find(c=>c.querySelector('.muted')?.textContent?.trim()==='Combined Hashrate');
    if(!card) return false;

    const valueEl=card.querySelector('.value');
    if(valueEl) valueEl.textContent=fmtHash(value);

    let note=card.querySelector('.hashrate-window-note');
    if(!note){
      note=document.createElement('div');
      note.className='small muted hashrate-window-note';
      card.appendChild(note);
    }
    const minutes=Math.max(1,Math.round(Number(windowSeconds||600)/60));
    note.textContent=`Rolling ${minutes}-minute estimate`;
    return true;
  }

  let busy=false;
  async function refresh(){
    if(busy || !location.pathname.startsWith('/account/')) return;
    busy=true;
    try{
      const r=await fetch('/api/account/'+encodeURIComponent(address),{cache:'no-store'});
      if(!r.ok) return;
      const x=await r.json();
      updateCard(x.combined_hashrate, x.hashrate_window_seconds);
    }catch(e){} finally {
      busy=false;
    }
  }

  // account() redraws the whole page every 30 seconds. Polling shortly after
  // each redraw is safer than a MutationObserver, which previously retriggered
  // itself whenever it updated the hashrate card.
  setTimeout(refresh,150);
  setInterval(refresh,5000);
})();
