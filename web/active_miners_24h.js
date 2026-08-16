(function(){
  const ACTIVE_WINDOW_SECONDS=24*60*60;

  function recentlyActive(item){
    return Number(item?.last_seen_at||0) >= Math.floor(Date.now()/1000)-ACTIVE_WINDOW_SECONDS;
  }

  const originalRenderMiners=window.renderMiners;
  if(typeof originalRenderMiners==='function'){
    window.renderMiners=function(miners){
      return originalRenderMiners((miners||[]).filter(recentlyActive));
    };
  }

  const originalWorkerBars=window.workerBars;
  if(typeof originalWorkerBars==='function'){
    window.workerBars=function(workers){
      return originalWorkerBars((workers||[]).filter(recentlyActive));
    };
  }

  if(location.pathname==='/miners' && typeof window.miners==='function'){
    window.miners();
  }else if(location.pathname==='/' && typeof window.dashboard==='function'){
    window.dashboard();
  }
})();
