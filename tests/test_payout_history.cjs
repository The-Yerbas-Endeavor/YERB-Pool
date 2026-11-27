const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(require('path').join(__dirname,'..','web','index.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
const app={innerHTML:''};
let data=[],requested;
const context={app,fetch:async url=>{requested=url;return {ok:true,json:async()=>data}}};
vm.createContext(context);
// Load the actual base helpers and route without starting browser timers.
vm.runInContext(script.slice(0,script.indexOf('function hashRate'))+
  script.slice(script.indexOf('function renderPayouts('),script.indexOf('async function account()')),context);
(async()=>{
  data=[{id:17,status:'sent',total_atomic:123000000,recipient_count:2,created_at:1700000000,sent_at:1700000100,txid:'abc123'},{id:18,status:'<pending>',total_atomic:0,recipient_count:0}];
  await context.payouts();
  assert.equal(requested,'/api/payouts?limit=500');
  assert.match(app.innerHTML,/href="\/payouts\?id=17"/);
  assert.match(app.innerHTML,/1\.23 YERB/);
  assert.match(app.innerHTML,/href="https:\/\/explorer\.yerbas\.org\/tx\/abc123"/);
  assert.match(app.innerHTML,/&lt;pending&gt;/);
  assert.match(app.innerHTML,/<td>2<\/td>/);
  data=[];await context.payouts();assert.match(app.innerHTML,/No payouts yet/);
  data={};await assert.rejects(context.payouts(),/Invalid payout history response/);
  console.log('Payout history renders populated and empty responses; invalid data rejected.');
})().catch(e=>{console.error(e);process.exitCode=1});
