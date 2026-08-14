(function(){
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

  function updateCard(value){
    const cards=[...document.querySelectorAll('main#app .card')];
    const card=cards.find(c=>c.querySelector('.muted')?.textContent?.trim()==='Combined Hashrate');
    if(!card) return;
    const valueEl=card.querySelector('.value');
    if(valueEl) valueEl.textContent=fmtHash(value);
    let note=card.querySelector('.hashrate-window-note');
    if(!note){
      note=document.createElement('div');
      note.className='small muted hashrate-window-note';
      card.appendChild(note);
    }
    note.textContent='Rolling 10-minute estimate';
  }

  async function refresh(){
    try{
      const r=await fetch('/api/account-hashrate/'+encodeURIComponent(address),{cache:'no-store'});
      if(!r.ok) return;
      const x=await r.json();
      updateCard(x.hashrate);
    }catch(e){}
  }

  const app=document.querySelector('main#app');
  if(app){
    const observer=new MutationObserver(()=>refresh());
    observer.observe(app,{childList:true,subtree:true});
  }
  setTimeout(refresh,250);
  setInterval(refresh,10000);
})();
