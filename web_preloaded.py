#!/usr/bin/env python3
"""Production web entry point for the YERB Pool dashboard."""

import mimetypes
import re
from http.server import ThreadingHTTPServer

import web_controls as controls


base = controls.enhanced.admin.live.base


class PreloadedControlHandler(controls.ControlHandler):
    def serve_file(self, target):
        if target != base.WEB_ROOT / "index.html":
            return super().serve_file(target)

        text = target.read_text()

        # Production labels.
        text = text.replace(
            "['Address','Workers','Accepted','Rejected','Balance','Immature','Total Paid']",
            "['Address','Workers','Accepted','Rejected','Mature Balance','Immature Balance','Total Paid']",
        )
        text = text.replace('<div class="muted">Immature</div>', '<div class="muted">Immature Balance</div>')
        text = text.replace('<div class="muted">Balance</div>', '<div class="muted">Mature Balance</div>')
        text = text.replace(
            "latest=h.slice(-2).reduce((s,v)=>s+Number(v.hashrate||0),0)/Math.max(1,Math.min(2,h.length))",
            "latest=Number(x.hashrate||x.combined_hashrate||0)",
        )

        # Dashboard-only context used by the native combined chart metric row.
        text = text.replace(
            "let selectedHashRange='24H';",
            "let selectedHashRange='24H';\n"
            "let dashboardHashContext={poolBalanceAtomic:0,immatureAtomic:0,totalPaidAtomic:0,miners:0,etaSeconds:null};",
            1,
        )
        text = text.replace(
            "const current=w.reduce((n,x)=>n+Number(x.active?x.hashrate:0),0),poolNow=Number(hash?.pool_hashrate||luck?.pool_hashrate||current);const cards=",
            "const current=w.reduce((n,x)=>n+Number(x.active?x.hashrate:0),0),poolNow=Number(hash?.pool_hashrate||luck?.pool_hashrate||current);"
            "dashboardHashContext={poolBalanceAtomic:Number(s.accounts.balance_atomic||0),immatureAtomic:Number(s.accounts.immature_atomic||0),totalPaidAtomic:Number(s.payouts.paid_atomic||0),miners:Number(s.accounts.accounts||0),etaSeconds:luck?.eta_seconds??null};"
            "const cards=",
            1,
        )

        # Worker mode: use the dashboard visual language, but never reuse the
        # dashboard's persisted network samples. Instead draw worker hashrate
        # with accepted/rejected share activity in the same full-width panel.
        worker_chart_js = r'''function workerChartSvg(history){const W=1120,H=340,L=72,R=24,T=22,B=46,iw=W-L-R,ih=H-T-B,rows=Array.isArray(history)?history:[];if(!rows.length)return'<div class="empty">No worker history recorded yet.</div>';const pmax=Math.max(...rows.map(x=>Number(x.hashrate||0)),1)*1.12,smax=Math.max(...rows.map(x=>Number(x.accepted||0)+Number(x.rejected||0)),1),min=Number(rows[0].ts||0),max=Number(rows[rows.length-1].ts||min+1),px=ts=>L+(Number(ts)-min)/Math.max(1,max-min)*iw,py=v=>T+ih-Number(v||0)/pmax*ih,pts=rows.map(x=>`${px(x.ts).toFixed(1)},${py(x.hashrate).toFixed(1)}`).join(' '),area=`${L},${T+ih} ${pts} ${W-R},${T+ih}`;let grid='',bars='',labels='';for(let i=0;i<=4;i++){const y=T+ih*i/4;grid+=`<line class="gridline" x1="${L}" y1="${y}" x2="${W-R}" y2="${y}"/><text class="axis pool-axis" x="4" y="${y+4}">${esc(hashRate(pmax*(1-i/4)))}</text>`}const bw=Math.max(2,Math.min(12,iw/Math.max(rows.length,1)*.58)),base=T+ih;for(const x of rows){const a=Number(x.accepted||0)/smax*ih*.24,r=Number(x.rejected||0)/smax*ih*.24,x0=px(x.ts)-bw/2;bars+=`<rect class="share-accepted" x="${x0.toFixed(1)}" y="${(base-a).toFixed(1)}" width="${bw.toFixed(1)}" height="${a.toFixed(1)}"/><rect class="share-rejected" x="${x0.toFixed(1)}" y="${(base-a-r).toFixed(1)}" width="${bw.toFixed(1)}" height="${r.toFixed(1)}"/>`}const count=selectedHashRange==='7D'?7:6;for(let i=0;i<count;i++){const ts=min+(max-min)*i/Math.max(1,count-1),x=px(ts),d=new Date(ts*1000),label=selectedHashRange==='7D'?d.toLocaleDateString([],{month:'short',day:'numeric'}):d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});labels+=`<text class="axis" text-anchor="${i===0?'start':i===count-1?'end':'middle'}" x="${x}" y="${H-10}">${esc(label)}</text>`}return `<div class="combined-chart-wrap"><svg class="combined-hash-chart worker-only-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<polygon class="pool-area" points="${area}"/>${bars}<polyline class="pool-line" points="${pts}"/>${labels}<line class="hash-crosshair" x1="0" x2="0" y1="${T}" y2="${T+ih}"/></svg><div class="combined-hash-tooltip" hidden></div></div>`}'''
        text = text.replace("function combinedHashChart(data,opts={}){", worker_chart_js + "\nfunction combinedHashChart(data,opts={}){", 1)
        text = text.replace(
            "poolNow=Number(data?.pool_hashrate||0),samples=networkSamples(networkNow),r=",
            "poolNow=Number(data?.pool_hashrate||0),workerMode=!!opts.workerMode,samples=workerMode?[]:networkSamples(networkNow),r=",
            1,
        )
        text = text.replace(",workerMode=!!opts.workerMode,accepted=", ",accepted=", 1)
        text = text.replace(
            "${hashChartSvg(history,rangeSamples,networkNow)}",
            "${workerMode?workerChartSvg(history):hashChartSvg(history,rangeSamples,networkNow)}",
            1,
        )
        text = text.replace(
            "const samples=networkSamples(Number(data.network_hashrate||0)),W=1120",
            "const samples=opts.workerId?[]:networkSamples(Number(data.network_hashrate||0)),W=1120",
            1,
        )
        text = text.replace(
            '<div class="hash-metric"><span>Accepted</span><strong>${accepted.toLocaleString()}</strong><small>${rejected.toLocaleString()} rejected</small></div><div class="hash-metric"><span>Efficiency</span>',
            '<div class="hash-metric"><span>Accepted</span><strong>${accepted.toLocaleString()}</strong></div><div class="hash-metric"><span>Rejected</span><strong>${rejected.toLocaleString()}</strong><small>${((accepted+rejected)>0?rejected/(accepted+rejected)*100:0).toFixed(2)}% reject rate</small></div><div class="hash-metric"><span>Efficiency</span>',
            1,
        )
        text = text.replace(
            '${workerMode?`<span><i class="hash-dot pool"></i>Worker hashrate</span>`:',
            '${workerMode?`<span><i class="hash-dot pool"></i>Worker hashrate</span><span><i class="dot okdot"></i>Accepted shares</span><span><i class="dot baddot"></i>Rejected shares</span>`:',
            1,
        )
        text = text.replace(
            "Worker hashrate with the same chart layout used on the dashboard.",
            "Worker hashrate and share activity over the selected time range.",
        )
        text = text.replace("Worker hashrate over selected range", "Worker hashrate and share activity over selected range")
        text = text.replace(
            "</style>",
            "#worker-hash-card .hash-metrics{grid-template-columns:repeat(4,minmax(130px,1fr))}"
            ".worker-only-chart .share-accepted{fill:rgba(101,196,102,.42)}"
            ".worker-only-chart .share-rejected{fill:rgba(255,120,120,.72)}"
            "@media(max-width:900px){#worker-hash-card .hash-metrics{grid-template-columns:repeat(2,minmax(130px,1fr))}}"
            "@media(max-width:520px){#worker-hash-card .hash-metrics{grid-template-columns:1fr}}"
            "</style>",
            1,
        )

        # Six dashboard metrics inside Network Hash vs Pool Hash.
        text = text.replace(
            ".hash-metrics{display:grid;grid-template-columns:repeat(3,minmax(130px,1fr));",
            ".hash-metrics{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));",
            1,
        )
        old_metrics = (
            '<div class="hash-metrics">'
            '<div class="hash-metric"><span>Pool now</span><strong>${hashRate(poolNow)}</strong><small>${selectedHashRange} average ${hashRate(ps.avg)}</small></div>'
            '<div class="hash-metric"><span>Network now</span><strong>${hashRate(networkNow)}</strong><small>${selectedHashRange} average ${hashRate(ns.avg)}</small></div>'
            '<div class="hash-metric"><span>Pool share</span><strong>${share.toFixed(2)}%</strong><small>of current network hash</small></div>'
            '</div>'
        )
        balance_metric = (
            '<div class="hash-metric"><span>Pool balance / Immature / Total paid</span>'
            '<strong>${coin(dashboardHashContext.poolBalanceAtomic)} / ${coin(dashboardHashContext.immatureAtomic)} / ${coin(dashboardHashContext.totalPaidAtomic)}</strong></div>'
        )
        new_metrics = (
            '<div class="hash-metrics">'
            '<div class="hash-metric"><span>Pool now</span><strong>${hashRate(poolNow)}</strong><small>${selectedHashRange} average ${hashRate(ps.avg)}</small></div>'
            '<div class="hash-metric"><span>Network now</span><strong>${hashRate(networkNow)}</strong><small>${selectedHashRange} average ${hashRate(ns.avg)}</small></div>'
            '<div class="hash-metric"><span>Pool share</span><strong>${share.toFixed(2)}%</strong><small>of current network hash</small></div>'
            + balance_metric +
            '<div class="hash-metric"><span>Miners</span><strong>${Number(dashboardHashContext.miners||0).toLocaleString()}</strong><small>tracked payout addresses</small></div>'
            '<div class="hash-metric"><span>Estimated block time</span><strong>${fmtTime(dashboardHashContext.etaSeconds)}</strong><small>at current pool hashrate</small></div>'
            '</div>'
        )
        text = text.replace(old_metrics, new_metrics, 1)
        text = re.sub(r'<div class="hash-metric"><span>Peak pool</span>.*?</div>', balance_metric, text, count=1)
        text = re.sub(
            r'<div class="hash-metric"><span>Peak network</span>.*?</div>',
            '<div class="hash-metric"><span>Miners</span><strong>${Number(dashboardHashContext.miners||0).toLocaleString()}</strong><small>tracked payout addresses</small></div><div class="hash-metric"><span>Estimated block time</span><strong>${fmtTime(dashboardHashContext.etaSeconds)}</strong><small>at current pool hashrate</small></div>',
            text,
            count=1,
        )

        # Never let recurring full-page redraws recreate the native charts.
        text = text.replace("if(location.pathname==='/')setInterval(dashboard,10000);", "")
        text = text.replace("if(location.pathname.startsWith('/worker/'))setInterval(worker,30000);", "")
        text = text.replace("if(location.pathname.startsWith('/account/'))setInterval(account,30000);", "")
        text = text.replace("</head>", '<link rel="stylesheet" href="/brand.css?v=1"></head>')

        # Filter legacy injected chart implementations at the production edge.
        luck_script = base.LUCK_SCRIPT
        luck_script = re.sub(
            r'<script[^>]+src=["\'][^"\']*(?:network_hash_chart|hashrate_chart_fast|hashrate_preload_bridge)\.js[^"\']*["\'][^>]*></script>',
            '',
            luck_script,
            flags=re.IGNORECASE,
        )
        luck_script = re.sub(r'setInterval\s*\(\s*renderLuck\s*,\s*10000\s*\)\s*;?', '', luck_script)
        luck_script = luck_script.replace("setTimeout(renderLuck,800); setInterval(renderLuck,10000);", "setTimeout(renderLuck,800);")

        body_text = text.replace(
            "</body>",
            luck_script
            + '<script src="/reward_labels.js?v=7"></script>'
            + '<script src="/account_performance.js?v=1"></script></body>',
        )
        body_text = re.sub(
            r'<script[^>]+src=["\'][^"\']*(?:network_hash_chart|hashrate_chart_fast|hashrate_preload_bridge)\.js[^"\']*["\'][^>]*></script>',
            '',
            body_text,
            flags=re.IGNORECASE,
        )
        body = body_text.encode()

        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    controls.ensure_user_control_schema(base.DB_PATH)
    controls._ensure_chart_index()
    print(
        f"YERB Pool web/admin listening on http://{base.HOST}:{base.PORT} "
        "(native dashboard/worker/account charts enabled; legacy chart loaders filtered)"
    )
    ThreadingHTTPServer((base.HOST, base.PORT), PreloadedControlHandler).serve_forever()
