(function(){
  const root=document.getElementById('admin-access-content');
  if(!root)return;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(body){
    const options=body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
    const response=await fetch('/api/admin/access/users',options),data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||response.statusText);
    return data;
  }
  function userRows(users){
    return users.map(user=>`<tr><td><strong>${esc(user.username)}</strong>${user.legacy_owner?' <span class="user-badge user-ok">Owner</span>':' <span class="user-badge">Admin</span>'}</td><td>${user.enabled?'<span class="user-badge user-ok">Enabled</span>':'<span class="user-badge user-paused">Disabled</span>'}</td><td>${user.created_at?new Date(Number(user.created_at)*1000).toLocaleString():'Original account'}</td><td>${user.legacy_owner?'<span class="muted">Use set-admin-password.py</span>':`<button data-toggle="${esc(user.username)}" data-enabled="${user.enabled?'0':'1'}">${user.enabled?'Disable':'Enable'}</button> <button data-password="${esc(user.username)}">Reset password</button> <button class="danger" data-delete="${esc(user.username)}">Remove</button><span data-password-form="${esc(user.username)}" hidden style="display:none;margin-top:7px"><input type="password" autocomplete="new-password" minlength="12" placeholder="New password (12+ characters)"> <button data-password-save="${esc(user.username)}">Save password</button></span>`}</td></tr>`).join('');
  }
  async function load(){
    try{
      const data=await api();
      if(!data.can_manage){root.innerHTML=`<div class="admin-card">Signed in as <strong>${esc(data.current_user)}</strong>. Only the owner can manage administrator accounts.</div>`;return;}
      root.innerHTML=`<div class="admin-card"><strong>Add administrator</strong><div class="muted" style="margin:5px 0 12px">New administrators can use the panel but cannot add or remove other administrators.</div><div style="display:flex;gap:9px;flex-wrap:wrap"><input id="new-admin-username" autocomplete="off" placeholder="Username" minlength="3" maxlength="32"><input id="new-admin-password" type="password" autocomplete="new-password" placeholder="Password (12+ characters)" minlength="12"><button id="add-admin-user">Add administrator</button></div><div id="admin-access-message" style="margin-top:9px"></div></div><div class="admin-user-table-wrap" style="margin-top:14px"><table><thead><tr><th>User</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead><tbody>${userRows(data.users||[])}</tbody></table></div>`;
      root.querySelector('#add-admin-user').onclick=async()=>{
        const username=root.querySelector('#new-admin-username').value.trim(),password=root.querySelector('#new-admin-password').value,message=root.querySelector('#admin-access-message');
        message.textContent='Adding…';
        try{await api({action:'add',username,password});await load();}catch(error){message.className='error';message.textContent=error.message;}
      };
      root.querySelectorAll('[data-toggle]').forEach(button=>button.onclick=async()=>{await api({action:'enabled',username:button.dataset.toggle,enabled:button.dataset.enabled==='1'});await load();});
      root.querySelectorAll('[data-password]').forEach(button=>button.onclick=()=>{const form=root.querySelector(`[data-password-form="${CSS.escape(button.dataset.password)}"]`);if(form){form.hidden=false;form.style.display='inline-block';form.querySelector('input').focus();}});
      root.querySelectorAll('[data-password-save]').forEach(button=>button.onclick=async()=>{const form=button.closest('[data-password-form]'),password=form.querySelector('input').value;try{await api({action:'password',username:button.dataset.passwordSave,password});await load();}catch(error){alert(error.message);}});
      root.querySelectorAll('[data-delete]').forEach(button=>button.onclick=async()=>{if(!confirm(`Remove administrator ${button.dataset.delete}?`))return;await api({action:'delete',username:button.dataset.delete});await load();});
    }catch(error){root.innerHTML=`<div class="admin-card error">${esc(error.message)}</div>`;}
  }
  load();
})();
