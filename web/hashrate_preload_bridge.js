(function(){
  if(location.pathname!=='/' || !window.__YERB_HASHRATE_PRELOAD__) return;
  if(typeof window.get!=='function') return;

  const originalGet=window.get;
  let preload=window.__YERB_HASHRATE_PRELOAD__;

  window.get=function(url){
    const u=String(url||'');
    if(preload && u.indexOf('/api/hashrate/chart?hours=24&bucket=600')===0){
      const p=preload;
      preload=null;
      return p;
    }
    return originalGet.apply(this,arguments);
  };
})();
