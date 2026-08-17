#!/usr/bin/env python3
"""Production web entry point for the YERB Pool dashboard.

The combined network/pool hashrate chart lives directly in web/index.html.
This wrapper applies production labels/branding and additive live widgets only.
Legacy chart injectors are explicitly filtered so they cannot replace the native
chart after the page has loaded.
"""

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
            "latest=h.slice(-2).reduce((s,v)=>s+Number(v.hashrate||0),0)/Math.max(1,Math.min(2,h.length))",
            "latest=Number(x.hashrate||x.combined_hashrate||0)",
        )

        # Give the native combined chart access to the non-hash dashboard
        # values that belong in its metric row. The context survives range
        # changes because only the chart data is re-fetched when a range button
        # is clicked.
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

        # Keep six useful metric cards inside Network Hash vs Pool Hash:
        # Pool now, Network now, Pool share, Pool balance / Immature / Total paid,
        # Miners, and Estimated block time. Explicitly remove any legacy
        # Peak pool / Peak network cards if they are present in the template.
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
            '<strong>${coin(dashboardHashContext.poolBalanceAtomic)} / ${coin(dashboardHashContext.immatureAtomic)} / ${coin(dashboardHashContext.totalPaidAtomic)} YERB</strong>'
            '<small>mature / immature / lifetime paid</small></div>'
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
        text = re.sub(
            r'<div class="hash-metric"><span>Peak pool</span>.*?</div>',
            balance_metric,
            text,
            count=1,
        )
        text = re.sub(
            r'<div class="hash-metric"><span>Peak network</span>.*?</div>',
            '<div class="hash-metric"><span>Miners</span><strong>${Number(dashboardHashContext.miners||0).toLocaleString()}</strong><small>tracked payout addresses</small></div><div class="hash-metric"><span>Estimated block time</span><strong>${fmtTime(dashboardHashContext.etaSeconds)}</strong><small>at current pool hashrate</small></div>',
            text,
            count=1,
        )

        # The native dashboard owns its combined chart and the old dashboard
        # metric strip has been removed from web/index.html. Never allow a
        # recurring full-dashboard redraw to destroy/recreate the chart.
        text = text.replace("if(location.pathname==='/')setInterval(dashboard,10000);", "")
        text = text.replace("if(location.pathname.startsWith('/worker/'))setInterval(worker,30000);", "")
        text = text.replace("if(location.pathname.startsWith('/account/'))setInterval(account,30000);", "")
        text = text.replace(
            "</head>",
            '<link rel="stylesheet" href="/brand.css?v=1"></head>',
        )

        # LUCK_SCRIPT is assembled additively through several imported web
        # layers. Older releases appended standalone chart renderers there.
        # Filter them at the final production boundary so an old renderer can
        # never wake up later and replace the native chart.
        luck_script = base.LUCK_SCRIPT
        luck_script = re.sub(
            r'<script[^>]+src=["\'][^"\']*(?:network_hash_chart|hashrate_chart_fast|hashrate_preload_bridge)\.js[^"\']*["\'][^>]*></script>',
            '',
            luck_script,
            flags=re.IGNORECASE,
        )
        luck_script = re.sub(
            r'setInterval\s*\(\s*renderLuck\s*,\s*10000\s*\)\s*;?',
            '',
            luck_script,
        )
        luck_script = luck_script.replace(
            "setTimeout(renderLuck,800); setInterval(renderLuck,10000);",
            "setTimeout(renderLuck,800);",
        )

        body_text = text.replace(
            "</body>",
            luck_script + '<script src="/reward_labels.js?v=7"></script></body>',
        )

        # Defense in depth: strip any legacy chart-loader tag that may already
        # exist in the source template itself. The only chart implementation on
        # the home page must be the one embedded in web/index.html.
        body_text = re.sub(
            r'<script[^>]+src=["\'][^"\']*(?:network_hash_chart|hashrate_chart_fast|hashrate_preload_bridge)\.js[^"\']*["\'][^>]*></script>',
            '',
            body_text,
            flags=re.IGNORECASE,
        )
        body = body_text.encode()

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
        "(native dashboard chart enabled; legacy chart loaders filtered)"
    )
    ThreadingHTTPServer((base.HOST, base.PORT), PreloadedControlHandler).serve_forever()
