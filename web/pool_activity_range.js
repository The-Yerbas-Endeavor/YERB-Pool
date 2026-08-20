(function(){
  if(location.pathname!=='/') return;

  const labels={
    '1H':'1 hour',
    '6H':'6 hours',
    '12H':'12 hours',
    '24H':'24 hours',
    '7D':'7 days'
  };

  function updatePoolActivityRange(key){
    const label=labels[key]||labels['24H'];
    const headings=[...document.querySelectorAll('main#app h1, main#app h2, main#app h3')];
    const heading=headings.find(h=>h.textContent.trim().toLowerCase().startsWith('pool activity'));
    if(!heading) return false;

    heading.textContent=`Pool Activity — last ${label}`;
    const section=heading.closest('section');
    const subtitle=section?.querySelector('.section-head .muted');
    if(subtitle) subtitle.textContent=`Pool-wide GhostRider share work recorded during the last ${label}.`;
    return true;
  }

  function activeRange(){
    return document.querySelector('#combined-hash-card [data-hash-range].active')?.dataset.hashRange
      || document.querySelector('[data-hash-range].active')?.dataset.hashRange
      || '24H';
  }

  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-hash-range]');
    if(!button || location.pathname!=='/') return;
    const key=button.dataset.hashRange;
    if(!labels[key]) return;
    requestAnimationFrame(()=>updatePoolActivityRange(key));
  });

  let attempts=0;
  const timer=setInterval(()=>{
    attempts++;
    if(updatePoolActivityRange(activeRange()) || attempts>=20) clearInterval(timer);
  },100);
})();

(function(){
  const path=location.pathname;
  const isBlocks=path==='/blocks'||path==='/blocks/pending';
  const isPayouts=path==='/payouts'&&!new URLSearchParams(location.search).has('id');
  if(!isBlocks&&!isPayouts) return;

  const PAGE_SIZE=25;
  let currentPage=Math.max(1,parseInt(new URLSearchParams(location.search).get('page')||'1',10)||1);
  let rows=[];
  let loading=false;

  function ensureStyles(){
    if(document.getElementById('yerb-pagination-styles')) return;
    const style=document.createElement('style');
    style.id='yerb-pagination-styles';
    style.textContent=`
      .yerb-pagination{display:flex;align-items:center;justify-content:center;gap:7px;flex-wrap:wrap;margin:18px 0 4px}
      .yerb-pagination button{min-width:34px;height:32px;padding:0 10px;border:1px solid #46534a;border-radius:7px;background:#1a201b;color:#dce8dd;font:inherit;font-size:12px;font-weight:700;cursor:pointer}
      .yerb-pagination button:hover:not(:disabled){border-color:#65c466;color:#f1fff2;background:#1c2920}
      .yerb-pagination button.active{border-color:#65c466;background:rgba(101,196,102,.16);color:#effff0;box-shadow:0 0 10px rgba(101,196,102,.12)}
      .yerb-pagination button:disabled{opacity:.35;cursor:default}
      .yerb-pagination-info{color:#829184;font-size:11px;margin:0 4px}
    `;
    document.head.appendChild(style);
  }

  function pageButtons(page,totalPages){
    const buttons=[];
    const start=Math.max(1,Math.min(page-2,totalPages-4));
    const end=Math.min(totalPages,Math.max(5,page+2));
    for(let p=start;p<=end;p++) buttons.push(`<button type="button" data-page="${p}" class="${p===page?'active':''}">${p}</button>`);
    return buttons.join('');
  }

  function pager(page,totalPages,totalRows){
    if(totalPages<=1) return `<div class="yerb-pagination-info" style="text-align:center;margin-top:14px">${totalRows.toLocaleString()} result${totalRows===1?'':'s'}</div>`;
    return `<div class="yerb-pagination"><button type="button" data-page="${page-1}" ${page<=1?'disabled':''}>← Prev</button>${pageButtons(page,totalPages)}<button type="button" data-page="${page+1}" ${page>=totalPages?'disabled':''}>Next →</button><span class="yerb-pagination-info">Page ${page} of ${totalPages} · ${totalRows.toLocaleString()} results</span></div>`;
  }

  function updateUrl(page){
    const u=new URL(location.href);
    if(page<=1) u.searchParams.delete('page');
    else u.searchParams.set('page',String(page));
    history.replaceState(null,'',u.pathname+(u.search?u.search:''));
  }

  function render(){
    const totalPages=Math.max(1,Math.ceil(rows.length/PAGE_SIZE));
    currentPage=Math.min(currentPage,totalPages);
    const start=(currentPage-1)*PAGE_SIZE;
    const items=rows.slice(start,start+PAGE_SIZE);
    const title=path==='/blocks/pending'?'Pending Blocks':isBlocks?'Blocks':'Payouts';
    const body=isBlocks?renderBlocks(items):renderPayouts(items);
    app.innerHTML=`<section><h2>${title}</h2>${body}${pager(currentPage,totalPages,rows.length)}</section>`;
    updateUrl(currentPage);
  }

  async function load(){
    if(loading) return;
    loading=true;
    ensureStyles();
    try{
      if(isBlocks){
        const pending=path==='/blocks/pending';
        rows=await get('/api/blocks?limit=500'+(pending?'&status=pending':''));
      }else{
        rows=await get('/api/payouts?limit=100');
      }
      render();
    }catch(e){
      app.innerHTML=`<div class="empty bad">${esc(e.message)}</div>`;
    }finally{
      loading=false;
    }
  }

  document.addEventListener('click',event=>{
    const button=event.target.closest('.yerb-pagination [data-page]');
    if(!button||button.disabled) return;
    const page=parseInt(button.dataset.page||'1',10);
    if(!Number.isFinite(page)||page<1) return;
    currentPage=page;
    render();
    window.scrollTo({top:0,behavior:'smooth'});
  });

  load();
})();

/* Preserve the last known miner block timestamp across account redraws.
   account_native.js currently derives the value from the newest share rows;
   once an older block-candidate share falls outside that response window the
   card can otherwise fall back to "Never". Keep the newest timestamp seen for
   this payout address and never replace it with an empty result. */
(function(){
  if(!location.pathname.startsWith('/account/')) return;

  const address=decodeURIComponent(location.pathname.slice('/account/'.length));
  const storageKey='yerbLastBlockFound:'+address;

  function readStored(){
    try{return Math.max(0,Number(localStorage.getItem(storageKey)||0)||0)}catch(_){return 0}
  }

  function writeStored(epoch){
    const value=Math.max(readStored(),Math.floor(Number(epoch)||0));
    if(!value) return;
    try{localStorage.setItem(storageKey,String(value))}catch(_){}
  }

  function ageSeconds(text){
    const s=String(text||'').trim().toLowerCase();
    if(!s||s==='never') return null;
    let total=0,matched=false,m;
    const re=/(\d+)\s*(d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)/g;
    while((m=re.exec(s))){
      matched=true;
      const n=Number(m[1]);
      const unit=m[2][0];
      total+=unit==='d'?n*86400:unit==='h'?n*3600:unit==='m'?n*60:n;
    }
    return matched?total:null;
  }

  function formatSince(epoch){
    const age=Math.max(0,Math.floor(Date.now()/1000-Number(epoch)));
    if(age<60) return `${age}s ago`;
    if(age<3600){const m=Math.floor(age/60),s=age%60;return `${m}m ${String(s).padStart(2,'0')}s ago`;}
    if(age<86400){const h=Math.floor(age/3600),m=Math.floor((age%3600)/60);return `${h}h ${String(m).padStart(2,'0')}m ago`;}
    const d=Math.floor(age/86400),h=Math.floor((age%86400)/3600);return `${d}d ${h}h ago`;
  }

  function sync(){
    const value=document.getElementById('account-last-block-value');
    const detail=document.getElementById('account-last-block-time');
    if(!value) return;

    const parsedAge=ageSeconds(value.textContent);
    if(parsedAge!==null){
      const observed=Math.floor(Date.now()/1000)-parsedAge;
      writeStored(observed);
    }

    const stored=readStored();
    if(!stored) return;

    const current=String(value.textContent||'').trim().toLowerCase();
    if(current==='never'||parsedAge===null){
      value.textContent=formatSince(stored);
      if(detail) detail.textContent=new Date(stored*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    }
  }

  const observer=new MutationObserver(sync);
  observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true});
  setInterval(sync,1000);
  setTimeout(sync,0);
})();
