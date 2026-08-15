#!/usr/bin/env python3
"""Production web entry point with deterministic enhanced Admin rendering."""

import json
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import web_enhanced as enhanced


FORCE_PAYOUT_REQUEST = Path("runtime") / "force_payout_request.json"
FORCE_PAYOUT_RESULT = Path("runtime") / "force_payout_result.json"


def _write_force_request(payload):
    FORCE_PAYOUT_REQUEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = FORCE_PAYOUT_REQUEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(FORCE_PAYOUT_REQUEST)


def _read_force_result():
    try:
        return json.loads(FORCE_PAYOUT_RESULT.read_text(encoding="utf-8"))
    except Exception:
        return {}


class ProductionHandler(enhanced.EnhancedHandler):
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/admin":
            if enhanced.admin._admin_enabled() and not self._require_admin():
                return
            html = enhanced.enhanced_admin_html()
            # Keep these explicit even if the underlying admin renderer changes.
            if "/admin_feed.js" not in html:
                html = html.replace(
                    "</body>",
                    '<script src="/admin_feed.js?v=2"></script></body>',
                )
            else:
                html = html.replace("/admin_feed.js?v=1", "/admin_feed.js?v=2")
            if "/admin_force_payout.js" not in html:
                html = html.replace(
                    "</body>",
                    '<script src="/admin_force_payout.js?v=1"></script></body>',
                )
            return self._send_html(html)
        if path == "/api/admin/payouts/force-status":
            if not self._require_admin():
                return
            return self.send_json(_read_force_result())
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/admin/payouts/force":
            if not self._require_admin():
                return
            if FORCE_PAYOUT_REQUEST.exists():
                return self.send_json({"error": "A force payout request is already queued"}, 409)
            request_id = uuid.uuid4().hex
            payload = {
                "request_id": request_id,
                "requested_at": int(time.time()),
            }
            try:
                _write_force_request(payload)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
            return self.send_json({"ok": True, **payload}, 202)
        return super().do_POST()


if __name__ == "__main__":
    print(
        f"YERB Pool production web listening on "
        f"http://{enhanced.admin.live.base.HOST}:{enhanced.admin.live.base.PORT}"
    )
    ThreadingHTTPServer(
        (enhanced.admin.live.base.HOST, enhanced.admin.live.base.PORT),
        ProductionHandler,
    ).serve_forever()
