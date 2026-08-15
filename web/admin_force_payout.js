(function(){
  if(location.pathname!=='/admin') return;

  function escForce(value){
    return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function install(){
    const payoutSection=[...document.querySelectorAll('section')].find(
      section=>section.querySelector('h2')?.textContent.trim()==='Payout configuration'
    );
    if(!payoutSection || document.getElementById('force-payout-card')) return;

    const card=document.createElement('div');
    card.id='force-payout-card';
    card.className='admin-card';
    card.style.marginTop='14px';
    card.innerHTML=`
      <div style="display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap">
        <div>
          <strong style="font-size:18px;margin:0 0 5px">Force Payout Now</strong>
          <div class="muted">Immediately run the normal payout check and send all currently eligible miners in one combined transaction batch.</div>
        </div>
        <button id="force-payout-now" type="button">Force Payout Now</button>
      </div>
      <div id="force-payout-message" class="muted" style="margin-top:12px"></div>`;
    payoutSection.appendChild(card);

    const button=document.getElementById('force-payout-now');
    const message=document.getElementById('force-payout-message');

    async function poll(requestId){
      for(let attempt=0;attempt<30;attempt++){
        await new Promise(resolve=>setTimeout(resolve,1000));
        try{
          const response=await fetch('/api/admin/payouts/force-status',{cache:'no-store'});
          const data=await response.json();
          if(!response.ok) throw new Error(data.error||'Unable to read payout status');
          if(data.request_id!==requestId || !data.completed_at) continue;
          if(data.ok){
            message.className='notice';
            const labels={sent:'Payout batch sent successfully.',no_eligible_miners:'No miners currently meet the minimum payout.',wallet_unavailable:'Wallet unavailable; no payout was sent.',deferred_fee_reserve:'Payout deferred because spendable funds do not exceed the fee reserve.',failed_before_broadcast:'Payout failed before broadcast.',uncertain:'Broadcast state is uncertain; manual reconciliation is required.',empty_batch:'No payout items were created.'};
            message.textContent=labels[data.result]||`Payout check completed: ${data.result||'checked'}.`;
          }else{
            message.className='error';
            message.textContent=data.error||'Forced payout failed.';
          }
          button.disabled=false;
          button.textContent='Force Payout Now';
          return;
        }catch(error){
          if(attempt===29){
            message.className='error';
            message.textContent=escForce(error.message);
          }
        }
      }
      button.disabled=false;
      button.textContent='Force Payout Now';
      if(!message.textContent || message.textContent.includes('requested')){
        message.className='muted';
        message.textContent='Payout request was accepted but is still processing. Check payout history shortly.';
      }
    }

    button.addEventListener('click',async()=>{
      if(!confirm('Run the payout check now and immediately broadcast a combined payout to all currently eligible miners?')) return;
      button.disabled=true;
      button.textContent='Requesting…';
      message.className='muted';
      message.textContent='Submitting immediate payout request…';
      try{
        const response=await fetch('/api/admin/payouts/force',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const data=await response.json();
        if(!response.ok) throw new Error(data.error||'Force payout request failed');
        message.textContent='Immediate payout requested. Waiting for the pool payout engine…';
        button.textContent='Processing…';
        poll(data.request_id);
      }catch(error){
        message.className='error';
        message.textContent=error.message;
        button.disabled=false;
        button.textContent='Force Payout Now';
      }
    });
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install);
  else install();
})();
