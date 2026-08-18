(function(){
  const COLORS={
    Confirmed:{color:'#9fe3a7',border:'#3d7f49',background:'rgba(70,150,82,.18)'},
    Pending:{color:'#ffd36a',border:'#8b6d25',background:'rgba(180,132,28,.18)'},
    Orphan:{color:'#ffaaaa',border:'#8f4444',background:'rgba(180,65,65,.18)'}
  };

  function paintBlockBadges(root=document){
    root.querySelectorAll('table tbody tr').forEach(row=>{
      const cells=row.querySelectorAll('td');
      if(cells.length<3)return;
      const badge=cells[1].querySelector('.badge');
      if(!badge)return;
      const label=badge.textContent.trim();
      const style=COLORS[label];
      if(!style)return;
      badge.style.color=style.color;
      badge.style.borderColor=style.border;
      badge.style.background=style.background;
      badge.style.fontWeight='700';
      const confirmation=cells[2];
      confirmation.style.color=style.color;
      confirmation.style.fontWeight='600';
    });
  }

  paintBlockBadges();
  const app=document.querySelector('main#app');
  if(app)new MutationObserver(()=>paintBlockBadges(app)).observe(app,{childList:true,subtree:true});
})();
