#!/usr/bin/env python3
"""Production web entry point with deterministic enhanced Admin rendering."""

from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

import web_enhanced as enhanced


class ProductionHandler(enhanced.EnhancedHandler):
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/admin":
            if enhanced.admin._admin_enabled() and not self._require_admin():
                return
            html = enhanced.enhanced_admin_html()
            # Keep this explicit even if the underlying admin renderer changes.
            if "/admin_feed.js" not in html:
                html = html.replace(
                    "</body>",
                    '<script src="/admin_feed.js?v=2"></script></body>',
                )
            else:
                html = html.replace("/admin_feed.js?v=1", "/admin_feed.js?v=2")
            return self._send_html(html)
        return super().do_GET()


if __name__ == "__main__":
    print(
        f"YERB Pool production web listening on "
        f"http://{enhanced.admin.live.base.HOST}:{enhanced.admin.live.base.PORT}"
    )
    ThreadingHTTPServer(
        (enhanced.admin.live.base.HOST, enhanced.admin.live.base.PORT),
        ProductionHandler,
    ).serve_forever()
