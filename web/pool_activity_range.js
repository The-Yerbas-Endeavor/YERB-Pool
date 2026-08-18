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
