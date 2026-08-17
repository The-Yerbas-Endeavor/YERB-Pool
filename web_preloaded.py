#!/usr/bin/env python3
"""Production web entry point for the YERB Pool dashboard.

The combined network/pool hashrate chart now lives directly in web/index.html.
This wrapper only applies production labels/branding and additive live widgets;
it no longer rewrites or injects the dashboard chart.
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
            "latest=h.slice(-2).reduce((s,v)=>s+Number(v.hashrate||0),0)/Math.max(1,Math.min(2,h.length))",
            "latest=Number(x.hashrate||x.combined_hashrate||0)",
        )

        # The base dashboard owns its combined chart and intentionally does not
        # rebuild the whole page on a timer. Do not inject a second chart loader.
        text = text.replace("if(location.pathname==='/')setInterval(dashboard,10000);", "")
        text = text.replace("if(location.pathname.startsWith('/worker/'))setInterval(worker,30000);", "")
        text = text.replace("if(location.pathname.startsWith('/account/'))setInterval(account,30000);", "")
        text = text.replace(
            "</head>",
            '<link rel="stylesheet" href="/brand.css?v=1"></head>',
        )

        # Keep the initial luck-panel population if present, but never redraw it
        # every 10 seconds because that causes visible page movement.
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
        "(native dashboard chart enabled)"
    )
    ThreadingHTTPServer((base.HOST, base.PORT), PreloadedControlHandler).serve_forever()
