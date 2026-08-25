(function(){
  const REQUIRED_CONFIRMATIONS=100;
  const PAGE_BLOCK_LIMIT=100;

  function ensureStyles(){
    if(document.getElementById('yerb-block-presentation-style')) return;
    const style=document.createElement('style');
    style.id='yerb-block-presentation-style';
    style.textContent=`
      .block-progress-wrap{min-width:118px}
      .block-progress-track{height:7px;border-radius:999px;background:#202720;overflow:hidden;margin-top:5px}
      .block-progress-fill{height:100%;background:#65c466;border-radius:999px;transition:width .2s ease}
      .block-progress-fill.pending{background:#d7b84b}
      .block-progress-fill.orphan{background:#697169}
      .block-status{font-weight:700}
      .block-status.pending{color:#ffe066}
      .block-status.mature{color:#8ee889}
      .block-status.orphan{color:#adb5bd}
      .block-finder{min-width:150px}
      .block-finder .small{margin-top:3px}
      @media(max-width:700px){
        .block-progress-wrap{min-width:100px}
        .block-finder{min-width:125px}
      }
    `;
    document.head.appendChild(style);
  }

  function blockState(x){
    const confirmations=Math.max(0,Number(x.confirmations||0));
    if(x.status==='orphan') return {label:'Orphaned',cls:'orphan',progress:0};
    if(x.status==='mature' || confirmations>=REQUIRED_CONFIRMATIONS){
      return {label:'Mature',cls:'mature',progress:100};
    }
    return {
      label:'Pending',
      cls:'pending',
      progress:Math.min(100,confirmations/REQUIRED_CONFIRMATIONS*100)
    };
  }

  function finderHtml(x,compact=false){
    const address=String(x.finder_address||'');
    const worker=String(x.finder_worker||'');
    if(!address && !worker) return '<span class="muted">—</span>';
    const addressPart=address
      ? `<a href="/account/${encodeURIComponent(address)}"><code>${esc(short(address))}</code></a>`
      : '<span class="muted">Unknown address</span>';
    if(compact || !worker) return addressPart;
    const workerPart=x.finder_worker_id
      ? `<a href="/worker/${encodeURIComponent(x.finder_worker_id)}"><code>${esc(worker)}</code></a>`
      : `<code>${esc(worker)}</code>`;
    return `<div class="block-finder">${addressPart}<div class="small muted">Worker ${workerPart}</div></div>`;
  }

  function progressHtml(x){
    const c=Math.max(0,Number(x.confirmations||0));
    const state=blockState(x);
    if(state.cls==='orphan') return '<span class="muted">—</span>';
    const shown=Math.min(c,REQUIRED_CONFIRMATIONS);
    return `<div class="block-progress-wrap"><strong>${shown} / ${REQUIRED_CONFIRMATIONS}</strong><div class="block-progress-track"><div class="block-progress-fill ${state.cls}" style="width:${state.progress.toFixed(1)}%"></div></div></div>`;
  }

  function foundHtml(x){
    if(!x.submitted_at) return '<span class="muted">—</span>';
    return `<span title="${esc(when(x.submitted_at))}">${ago(x.submitted_at)}</span><div class="small muted">${when(x.submitted_at)}</div>`;
  }

  function heightHtml(x){
    if(x.height===undefined || x.height===null) return '<span class="muted">—</span>';
    const blockRef=x.block_hash||x.height;
    return `<a href="${EXPLORER}/block/${encodeURIComponent(blockRef)}" target="_blank" rel="noopener"><strong>${Number(x.height).toLocaleString()}</strong></a>`;
  }

  function fullTable(blocks){
    const shown=blocks.slice(0,PAGE_BLOCK_LIMIT);
    if(!shown.length) return '<div class="empty">No blocks found yet.</div>';
    return table(
      ['Height','Found','Status','Maturity','Pool Reward','Finder','Hash'],
      shown.map(x=>{
        const state=blockState(x);
        return `<tr>
          <td>${heightHtml(x)}</td>
          <td>${foundHtml(x)}</td>
          <td><span class="block-status ${state.cls}">${state.label}</span></td>
          <td>${progressHtml(x)}</td>
          <td>${coin(x.reward_atomic)} YERB</td>
          <td>${finderHtml(x)}</td>
          <td>${explorerBlock(x.block_hash)}</td>
        </tr>`;
      })
    );
  }

  function compactTable(blocks){
    if(!blocks.length) return '<div class="empty">No blocks found yet.</div>';
    return table(
      ['Height','Status','Progress','Finder'],
      blocks.map(x=>{
        const state=blockState(x);
        return `<tr>
          <td>${heightHtml(x)}<div class="small muted">${x.submitted_at?ago(x.submitted_at):''}</div></td>
          <td><span class="block-status ${state.cls}">${state.label}</span></td>
          <td>${progressHtml(x)}</td>
          <td>${finderHtml(x,true)}</td>
        </tr>`;
      })
    );
  }

  function installRenderer(){
    ensureStyles();
    window.renderBlocks=function(blocks){
      return location.pathname==='/' ? compactTable(blocks) : fullTable(blocks);
    };
  }

  async function refreshVisibleTable(){
    try{
      if(location.pathname==='/'){
        const heading=[...document.querySelectorAll('main#app h2')]
          .find(h=>h.textContent.trim()==='Recent Blocks');
        const section=heading?.closest('section');
        if(!section) return;
        const blocks=await get('/api/blocks?limit=10');
        const old=section.querySelector('.table-wrap,.empty');
        const holder=document.createElement('div');
        holder.innerHTML=compactTable(blocks);
        if(old) old.replaceWith(holder.firstElementChild);
        return;
      }

      // Full block pages are populated by the server-backed pagination layer.
    }catch(e){}
  }

  function install(){
    installRenderer();
    refreshVisibleTable();
  }

  // reward_labels.js is injected after this file and also defines renderBlocks.
  // Install on the next task so this presentation layer intentionally wins.
  setTimeout(install,0);
})();
