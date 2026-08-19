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

/* Mouse-wheel zoom + drag-to-pan for all native hashrate/performance charts.
   The existing range buttons still control the amount of data fetched. Zoom
   is purely client-side and resets automatically whenever a chart is rebuilt. */
(function(){
  'use strict';

  const NS='http://www.w3.org/2000/svg';
  const PLOT_SELECTOR=[
    '.pool-area','.network-area','.pool-line','.network-line',
    '.share-accepted','.share-rejected','.pool-block-bar','.block-bar',
    '.account-worker-line','.account-combined-line'
  ].join(',');

  function ensureStyles(){
    if(document.getElementById('yerb-chart-zoom-styles')) return;
    const style=document.createElement('style');
    style.id='yerb-chart-zoom-styles';
    style.textContent=`
      .combined-chart-wrap.yerb-zoom-ready{position:relative}
      .combined-chart-wrap.yerb-zoom-ready .combined-hash-chart{cursor:crosshair;touch-action:none}
      .combined-chart-wrap.yerb-zoom-ready.yerb-panning .combined-hash-chart{cursor:grabbing}
      .yerb-chart-zoom-tools{position:absolute;z-index:8;right:10px;bottom:8px;display:flex;align-items:center;gap:7px;pointer-events:none;font-size:10px;color:#8c9b90;background:rgba(10,14,11,.78);border:1px solid rgba(65,86,70,.7);border-radius:7px;padding:4px 6px;backdrop-filter:blur(4px)}
      .yerb-chart-zoom-tools button{pointer-events:auto;border:1px solid #486050;border-radius:5px;background:#19211b;color:#d9e5db;padding:2px 6px;font:inherit;cursor:pointer}
      .yerb-chart-zoom-tools button:hover{border-color:#7a9d82;color:#fff}
      .yerb-chart-zoom-tools button[hidden]{display:none}
      .yerb-chart-zoom-level{min-width:34px;text-align:right;font-variant-numeric:tabular-nums}
      @media(max-width:620px){.yerb-chart-zoom-help{display:none}.yerb-chart-zoom-tools{right:6px;bottom:5px}}
    `;
    document.head.appendChild(style);
  }

  function geometry(svg){
    const vb=(svg.getAttribute('viewBox')||'0 0 1120 340').trim().split(/\s+/).map(Number);
    const W=Number.isFinite(vb[2])&&vb[2]>0?vb[2]:1120;
    const H=Number.isFinite(vb[3])&&vb[3]>0?vb[3]:340;
    const L=svg.classList.contains('chart')?52:72;
    const R=svg.classList.contains('worker-only-chart')?72:(svg.classList.contains('account-worker-chart')?24:78);
    return {W,H,L,R};
  }

  function pointCount(svg){
    let count=0;
    svg.querySelectorAll('polyline').forEach(line=>{
      const n=(line.getAttribute('points')||'').trim().split(/\s+/).filter(Boolean).length;
      if(n>count) count=n;
    });
    return count;
  }

  function setup(svg){
    if(!svg||svg.dataset.yerbZoomReady==='1'||!svg.matches('.combined-hash-chart')) return;
    const nodes=[...svg.querySelectorAll(PLOT_SELECTOR)].filter(node=>node.parentNode===svg);
    if(!nodes.length) return;

    ensureStyles();
    const {W,H,L,R}=geometry(svg);
    const visibleWidth=Math.max(1,W-L-R);
    const count=pointCount(svg);
    const maxScale=Math.max(1,Math.min(16,count>8?count/8:1));
    const state={scale:1,tx:0,W,H,L,R,maxScale,dragging:false,pointerId:null,startClientX:0,startTx:0};
    svg.__yerbZoomState=state;
    svg.dataset.yerbZoomReady='1';

    const defs=document.createElementNS(NS,'defs');
    const clip=document.createElementNS(NS,'clipPath');
    const clipId='yerb-plot-clip-'+Math.random().toString(36).slice(2);
    clip.setAttribute('id',clipId);
    const rect=document.createElementNS(NS,'rect');
    rect.setAttribute('x',L);rect.setAttribute('y',0);rect.setAttribute('width',visibleWidth);rect.setAttribute('height',H);
    clip.appendChild(rect);defs.appendChild(clip);svg.insertBefore(defs,svg.firstChild);

    const layer=document.createElementNS(NS,'g');
    layer.classList.add('yerb-chart-zoom-layer');
    layer.setAttribute('clip-path',`url(#${clipId})`);
    svg.insertBefore(layer,nodes[0]);
    nodes.forEach(node=>layer.appendChild(node));
    state.layer=layer;

    const wrap=svg.closest('.combined-chart-wrap');
    if(!wrap) return;
    wrap.classList.add('yerb-zoom-ready');
    const tools=document.createElement('div');
    tools.className='yerb-chart-zoom-tools';
    tools.innerHTML='<span class="yerb-chart-zoom-help">Scroll to zoom · Drag to pan · Double-click reset</span><span class="yerb-chart-zoom-level">100%</span><button type="button" hidden>Reset</button>';
    wrap.appendChild(tools);
    const level=tools.querySelector('.yerb-chart-zoom-level');
    const resetButton=tools.querySelector('button');

    function clampTx(tx,scale=state.scale){
      const min=(W-R)-scale*(W-R);
      const max=L-scale*L;
      return Math.max(min,Math.min(max,tx));
    }

    function apply(){
      state.tx=clampTx(state.tx);
      layer.setAttribute('transform',`translate(${state.tx.toFixed(3)} 0) scale(${state.scale.toFixed(5)} 1)`);
      const zoomed=state.scale>1.0001;
      level.textContent=Math.round(state.scale*100)+'%';
      resetButton.hidden=!zoomed;
      wrap.classList.toggle('yerb-zoomed',zoomed);
    }

    function reset(){
      state.scale=1;state.tx=0;apply();
      const tip=wrap.querySelector('.combined-hash-tooltip');
      const cross=svg.querySelector('.hash-crosshair');
      if(tip) tip.hidden=true;
      if(cross) cross.style.opacity='0';
    }

    svg.addEventListener('wheel',event=>{
      if(maxScale<=1) return;
      event.preventDefault();
      const box=svg.getBoundingClientRect();
      const cursor=Math.max(L,Math.min(W-R,(event.clientX-box.left)/Math.max(1,box.width)*W));
      const factor=event.deltaY<0?1.22:1/1.22;
      const next=Math.max(1,Math.min(maxScale,state.scale*factor));
      if(Math.abs(next-state.scale)<1e-5) return;
      state.tx=cursor-(next/state.scale)*(cursor-state.tx);
      state.scale=next;
      apply();
    },{passive:false});

    svg.addEventListener('pointerdown',event=>{
      if(event.button!==0||state.scale<=1.0001) return;
      state.dragging=true;state.pointerId=event.pointerId;state.startClientX=event.clientX;state.startTx=state.tx;
      wrap.classList.add('yerb-panning');
      svg.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    });
    svg.addEventListener('pointermove',event=>{
      if(!state.dragging||event.pointerId!==state.pointerId) return;
      const box=svg.getBoundingClientRect();
      state.tx=state.startTx+(event.clientX-state.startClientX)/Math.max(1,box.width)*W;
      apply();
      event.preventDefault();
    });
    const endDrag=event=>{
      if(!state.dragging||(event.pointerId!==undefined&&event.pointerId!==state.pointerId)) return;
      state.dragging=false;state.pointerId=null;wrap.classList.remove('yerb-panning');
    };
    svg.addEventListener('pointerup',endDrag);
    svg.addEventListener('pointercancel',endDrag);
    svg.addEventListener('lostpointercapture',endDrag);
    svg.addEventListener('dblclick',event=>{event.preventDefault();reset();});
    resetButton.addEventListener('click',reset);

    /* Existing hover handlers calculate from the unzoomed SVG. While zoomed,
       translate the mouse position back into source coordinates, let the
       existing handler choose the data point, then move its crosshair/tooltip
       forward into the zoomed display coordinate. */
    svg.addEventListener('mousemove',event=>{
      if(event._yerbZoomSynthetic||state.scale<=1.0001||state.dragging) return;
      event.stopImmediatePropagation();
      const box=svg.getBoundingClientRect();
      const displayX=(event.clientX-box.left)/Math.max(1,box.width)*W;
      const sourceX=(displayX-state.tx)/state.scale;
      const clientX=box.left+sourceX/W*box.width;
      const synthetic=new MouseEvent('mousemove',{
        bubbles:false,cancelable:true,view:window,clientX,clientY:event.clientY,
        screenX:event.screenX,screenY:event.screenY,ctrlKey:event.ctrlKey,
        shiftKey:event.shiftKey,altKey:event.altKey,metaKey:event.metaKey,buttons:event.buttons
      });
      Object.defineProperty(synthetic,'_yerbZoomSynthetic',{value:true});
      svg.dispatchEvent(synthetic);
      requestAnimationFrame(()=>{
        const cross=svg.querySelector('.hash-crosshair');
        if(cross){
          const source=Number(cross.getAttribute('x1'));
          if(Number.isFinite(source)){
            const shown=state.tx+state.scale*source;
            cross.setAttribute('x1',shown);cross.setAttribute('x2',shown);
            const tip=wrap.querySelector('.combined-hash-tooltip');
            if(tip&&!tip.hidden) tip.style.left=`${shown/W*100}%`;
          }
        }
      });
    },true);

    apply();
  }

  function scan(root=document){
    root.querySelectorAll?.('.combined-hash-chart').forEach(setup);
    if(root.matches?.('.combined-hash-chart')) setup(root);
  }

  scan();
  new MutationObserver(records=>{
    for(const record of records){
      record.addedNodes.forEach(node=>{if(node.nodeType===1) scan(node);});
    }
  }).observe(document.documentElement,{childList:true,subtree:true});
})();
