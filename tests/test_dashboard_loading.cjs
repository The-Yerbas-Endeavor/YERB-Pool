const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(require('path').join(__dirname,'..','web','index.html'),'utf8');
const fn=html.slice(html.indexOf('async function dashboard()'),html.indexOf('\nasync function miners()'));
const elements={}, pending={};
const app={firstElementChild:null,set innerHTML(value){this.html=value;this.firstElementChild={}; for(const id of ['dashboard-metrics','dashboard-blocks','dashboard-workers','combined-hash-card']) elements[id]={innerHTML:'Loading…'};}};
const context={app,document:{getElementById:id=>elements[id]},AbortController,setTimeout,clearTimeout,Promise,Number,
 fetch:(url)=>new Promise((resolve,reject)=>{pending[url]={resolve:data=>resolve({ok:true,json:async()=>data}),reject}}),
 updateDashboardContext:()=>{},hashRate:x=>String(x),coin:x=>String(x),workerBars:x=>'workers:'+x.length,renderBlocks:x=>'blocks:'+x.length,combinedHashChart:()=> 'chart',bindHashChart:()=>{}};
vm.createContext(context);vm.runInContext(fn+';this.dashboard=dashboard',context);
(async()=>{
 const done=context.dashboard();
 assert.match(app.html,/Loading/);
 pending['/api/blocks?limit=10'].resolve([{}]);
 await new Promise(setImmediate);
 assert.equal(elements['dashboard-blocks'].innerHTML,'blocks:1');
 assert.equal(elements['dashboard-metrics'].innerHTML,'Loading…');
 pending['/api/summary'].resolve({accounts:{accounts:1,balance_atomic:2,immature_atomic:3},workers:{active_workers:1},shares:{accepted:1,rejected:0},blocks:{blocks:1,pending:0},payouts:{paid_atomic:0}});
 pending['/api/hashrate/chart?hours=24&bucket=600'].resolve({pool_hashrate:0});
 pending['/api/workers?limit=50'].reject(new Error('unavailable'));
 pending['/api/luck'].resolve({pool_hashrate:123});
 await done;
 assert.equal(elements['combined-hash-card'].innerHTML,'chart');
 assert.match(elements['dashboard-workers'].innerHTML,/Data unavailable/);
 assert.match(elements['dashboard-metrics'].innerHTML,/Pool Hashrate<\/div><div class="value">0<\/div>/);
 assert.equal(elements['dashboard-blocks'].innerHTML,'blocks:1');
 console.log('Dashboard renders fast sections while summary waits; failures stay local; zero hashrate stays zero.');
})().catch(e=>{console.error(e);process.exitCode=1});
