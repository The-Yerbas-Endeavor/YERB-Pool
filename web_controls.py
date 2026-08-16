#!/usr/bin/env python3
"""Production web entry point with authenticated payout controls."""

from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

import web_enhanced as enhanced
from yerbpool.payout_control import (
    read_control,
    read_request_state,
    read_result,
    request_run_now,
    set_paused,
)


enhanced.admin.live.base.LUCK_SCRIPT += '<script src="/active_miners_24h.js?v=1"></script>'


def _control_snapshot():
    scheduler = enhanced.read_payout_status(enhanced.ROOT)
    control = read_control()
    return {
        "enabled": bool(scheduler.get("enabled", True)),
        "paused": bool(control.get("paused", scheduler.get("paused", False))),
        "interval_seconds": int(scheduler.get("interval_seconds") or 0),
        "next_check_at": int(scheduler.get("next_check_at") or 0),
        "last_check_at": int(scheduler.get("last_check_at") or 0),
        "last_result": scheduler.get("last_result") or "waiting",
        "request": read_request_state(),
        "last_manual_result": read_result(),
    }


def _admin_snapshot():
    data = enhanced.admin._admin_snapshot()
    treasury = data.get("treasury") or {}
    treasury["activity"] = list(treasury.get("activity") or [])[:10]
    data["treasury"] = treasury
    return data


class ControlHandler(enhanced.EnhancedHandler):
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/admin":
            if enhanced.admin._admin_enabled() and not self._require_admin():
                return
            html = enhanced.admin._admin_html()
            if "/admin_payout_controls.js" not in html:
                html = html.replace(
                    "</body>",
                    '<script src="/admin_payout_controls.js?v=1"></script></body>',
                )
            return self._send_html(html)
        if path == "/api/admin/settings":
            if not self._require_admin():
                return
            return self.send_json(_admin_snapshot())
        if path == "/api/admin/payouts/control":
            if not self._require_admin():
                return
            return self.send_json(_control_snapshot())
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/admin/payouts/pause":
            if not self._require_admin():
                return
            try:
                payload = self._read_json()
                if "paused" not in payload:
                    return self.send_json({"error": "paused is required"}, 400)
                state = set_paused(bool(payload["paused"]))
                return self.send_json({"ok": True, **state})
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        if path == "/api/admin/payouts/run-now":
            if not self._require_admin():
                return
            snapshot = _control_snapshot()
            if snapshot["paused"]:
                return self.send_json({"error": "Payouts are paused. Resume payouts before running a check."}, 409)
            if not snapshot["enabled"]:
                return self.send_json({"error": "Payout scheduler is disabled in configuration."}, 409)
            try:
                request = request_run_now()
                return self.send_json({"ok": True, **request}, 202)
            except RuntimeError as exc:
                return self.send_json({"error": str(exc)}, 409)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        return super().do_POST()


if __name__ == "__main__":
    print(
        f"YERB Pool web/admin listening on http://{enhanced.admin.live.base.HOST}:{enhanced.admin.live.base.PORT} "
        "(health diagnostics and payout controls enabled)"
    )
    ThreadingHTTPServer(
        (enhanced.admin.live.base.HOST, enhanced.admin.live.base.PORT), ControlHandler
    ).serve_forever()
