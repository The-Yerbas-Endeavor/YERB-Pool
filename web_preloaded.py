#!/usr/bin/env python3
"""Production web entry point with immediate hashrate-chart preload.

The chart request and chart renderer are both loaded from <head>, before the
base dashboard JavaScript launches its larger Promise.all() request fanout.
This prevents the tiny renderer asset itself from being queued behind dashboard
API traffic on HTTP/1.1.
"""

import mimetypes
from http.server import ThreadingHTTPServer

import web_controls as controls


base = controls.enhanced.admin.live.base


class PreloadedControlHandler(controls.ControlHandler):
    def serve_file(self, target):
        if target != base.WEB_ROOT / "index.html":
            return super().serve_file(target)

        text = target.read_text()
        text = text.replace(
            "['Address','Workers','Accepted','Rejected','Balance','Immature','Total Paid']",
            "['Address','Workers','Accepted','Rejected','Mature Balance','Immature Balance','Total Paid']",
        )
        text = text.replace(
            '<div class="muted">Immature</div>',
            '<div class="muted">Immature Balance</div>',
        )
        text = text.replace(
            '<div class="muted">Balance</div>',
            '<div class="muted">Mature Balance</div>',
        )
        text = text.replace(
            "const active=w.filter(x=>x.active).slice(0,24);const stats=(await Promise.all(active.map(x=>get('/api/worker/'+x.id+'/stats?hours=24&bucket=300').catch(()=>null)))).filter(Boolean);const h=aggregateHistory(stats);",
            "const h=[];",
        )
        text = text.replace(
            "const cards=[['Miners',s.accounts.accounts,'/miners'],['Active Workers',s.workers.active_workers,'/workers'],",
            "const cards=[['Miners / Active',`${s.accounts.accounts} / ${s.workers.active_workers}`,'/miners'],",
        )
        text = text.replace(
            "['Blocks Found',s.blocks.blocks,'/blocks'],['Pending Blocks',s.blocks.pending,'/blocks/pending'],",
            "",
        )
        text = text.replace(
            '<div class="metric"><span class="muted small">Rejected shares / 24h</span><strong>${rejected24.toLocaleString()}</strong></div>',
            '<a class="metric" href="/miners" style="display:block;color:inherit;text-decoration:none"><span class="muted small">Miners / Active</span><strong>${s.accounts.accounts} / ${s.workers.active_workers}</strong></a>',
        )
        text = text.replace(
            '<div class="metric"><span class="muted small">24h peak hashrate</span><strong>${hashRate(peak)}</strong></div>',
            '<a class="metric" href="/blocks" style="display:block;color:inherit;text-decoration:none"><span class="muted small">Blocks / Pending</span><strong>${s.blocks.blocks} / ${s.blocks.pending}</strong></a>',
        )

        old_dashboard_charts = '<div class="chart-grid" style="margin-top:16px"><div class="chart-card"><h3>Pool Hashrate</h3><div class="muted small">24-hour estimated hashrate in 5-minute buckets.</div>${h.length?lineChart(h,\'hashrate\',hashRate):\'<div class="empty">Waiting for enough accepted-share history.</div>\'}<div class="legend"><span><i class="dot hashdot"></i>Pool hashrate</span></div></div><div class="chart-card"><h3>Share Activity</h3><div class="muted small">Accepted and rejected shares in 5-minute buckets.</div>${h.length?shareChart(h):\'<div class="empty">Waiting for share history.</div>\'}<div class="legend"><span><i class="dot okdot"></i>Accepted</span><span><i class="dot baddot"></i>Rejected</span></div></div></div>'
        new_dashboard_chart = '<div class="chart-grid" style="margin-top:16px;grid-template-columns:1fr"><div class="chart-card"><h3>Pool Hashrate</h3><div class="muted small">Loading pool and network hashrate…</div><div class="empty" style="margin-top:12px">Loading chart…</div></div></div>'
        text = text.replace(old_dashboard_charts, new_dashboard_chart)

        text = text.replace(
            "latest=h.slice(-2).reduce((s,v)=>s+Number(v.hashrate||0),0)/Math.max(1,Math.min(2,h.length))",
            "latest=Number(x.hashrate||x.combined_hashrate||0)",
        )
        text = text.replace(
            "Accepted GhostRider share work from currently tracked workers.",
            "Pool-wide GhostRider share work recorded during the last 24 hours.",
        )

        # Never rebuild the entire dashboard on a timer. Full app.innerHTML
        # replacement caused a visible flash and also destroyed/recreated the
        # chart DOM. Live widgets update themselves independently.
        text = text.replace("if(location.pathname==='/')setInterval(dashboard,10000);", "")
        text = text.replace("if(location.pathname.startsWith('/worker/'))setInterval(worker,30000);", "")
        text = text.replace("if(location.pathname.startsWith('/account/'))setInterval(account,30000);", "")

        preload = '''<script>
if(location.pathname==='/'){
  window.__YERB_HASHRATE_PRELOAD__=fetch('/api/hashrate/chart?hours=24&bucket=600',{
    cache:'no-store',credentials:'same-origin'
  }).then(function(r){return r.ok?r.json():null}).catch(function(){return null});
}
</script><script src="/hashrate_chart_fast.js?v=3"></script>'''
        text = text.replace(
            "</head>",
            '<link rel="stylesheet" href="/brand.css?v=1">' + preload + "</head>",
        )

        # The legacy luck panel used to rewrite its entire panel every 10
        # seconds. That redraw was visible as a page flash. Keep its initial
        # population, but disable the recurring DOM rebuild. Other live status
        # components continue refreshing without replacing the page structure.
        luck_script = base.LUCK_SCRIPT.replace(
            "setTimeout(renderLuck,800); setInterval(renderLuck,10000);",
            "setTimeout(renderLuck,800);",
        )

        body = text.replace(
            "</body>",
            luck_script + '<script src="/reward_labels.js?v=6"></script></body>',
        ).encode()

        self.send_response(200)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    controls.ensure_user_control_schema(base.DB_PATH)
    controls._ensure_chart_index()
    print(
        f"YERB Pool web/admin listening on http://{base.HOST}:{base.PORT} "
        "(priority hashrate preload enabled)"
    )
    ThreadingHTTPServer((base.HOST, base.PORT), PreloadedControlHandler).serve_forever()
