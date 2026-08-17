#!/usr/bin/env python3
"""Production web entry point with authenticated payout and user controls."""

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
from yerbpool.user_controls import (
    ensure_user_control_schema,
    list_users,
    set_account_payout_enabled,
    set_account_suspended,
    set_ip_banned,
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


def _hashrate_from_diff(diff, seconds):
    return (
        (float(diff or 0) / enhanced.admin.live.base.GHOSTRIDER_TARGET_FACTOR)
        * enhanced.admin.live.base.DIFF1_HASHES
        / max(1, int(seconds))
    )


def _users_snapshot():
    path = enhanced.admin.live.base.DB_PATH
    treasury_address = enhanced.admin._treasury_address()
    window = enhanced.admin.live.HASHRATE_WINDOW
    users = list_users(path, window, treasury_address)
    for user in users:
        current_diff = float(user.pop("current_accepted_diff", 0) or 0)
        diff_24h = float(user.pop("accepted_diff_24h", 0) or 0)
        user["hashrate"] = _hashrate_from_diff(current_diff, window)
        user["hashrate_24h"] = _hashrate_from_diff(diff_24h, 86400)
        accepted = int(user.get("accepted_shares") or 0)
        rejected = int(user.get("rejected_shares") or 0)
        total = accepted + rejected
        user["rejection_percent"] = (rejected / total * 100.0) if total else 0.0
    return {
        "users": users,
        "hashrate_window_seconds": window,
        "average_hashrate_window_seconds": 86400,
    }


def _inject_user_admin(html):
    if 'id="admin-users"' not in html:
        users_section = (
            '<section><div style="display:flex;justify-content:space-between;align-items:end;gap:12px;flex-wrap:wrap">'
            '<div><h2 style="margin-bottom:4px">Users</h2>'
            '<div class="muted">Miner accounts, balances, current and 24-hour hashrate, IP location, share quality, payout status and mining controls.</div></div>'
            '</div><div id="admin-users"><div class="admin-card">Loading users…</div></div></section>'
        )
        html = html.replace('<section><h2>Payout configuration</h2>', users_section + '<section><h2>Payout configuration</h2>')
    if "/admin_users.js" not in html:
        extra = '''<style>
#admin-users{margin-top:14px}.user-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px}.user-toolbar input{width:min(520px,80vw)}.admin-user-table-wrap{overflow-x:auto}.admin-user-table{min-width:2350px}.admin-user-table td{vertical-align:top;white-space:nowrap}.admin-user-table td.user-address,.admin-user-table td.user-ips{white-space:normal}.user-small{font-size:11px;margin-top:4px}.admin-ip{margin-bottom:10px}.user-badge{display:inline-block;padding:3px 7px;border-radius:999px;border:1px solid #444;font-size:11px;font-weight:700}.user-ok{color:#9fe3a7;border-color:#376c41;background:#152719}.user-paused{color:#ffe08a;border-color:#6d5d2b;background:#29240f}.user-banned,.user-suspended{color:#ffaaaa;border-color:#7b3737;background:#2b1515}.user-control-btn,.user-mini-btn{padding:6px 9px;font-size:11px}.user-mini-btn{margin-left:6px}.danger{background:#8a3434}button:disabled{opacity:.55;cursor:wait}
</style><script src="/admin_users.js?v=2"></script>'''
        html = html.replace("</body>", extra + "</body>")
    return html


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
            html = _inject_user_admin(html)
            return self._send_html(html)
        if path == "/api/admin/settings":
            if not self._require_admin():
                return
            return self.send_json(_admin_snapshot())
        if path == "/api/admin/payouts/control":
            if not self._require_admin():
                return
            return self.send_json(_control_snapshot())
        if path == "/api/admin/users":
            if not self._require_admin():
                return
            try:
                return self.send_json(_users_snapshot())
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
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
        if path == "/api/admin/users/payment":
            if not self._require_admin():
                return
            try:
                payload = self._read_json()
                enabled = payload.get("enabled")
                if not isinstance(enabled, bool):
                    return self.send_json({"error": "enabled must be true or false"}, 400)
                address = str(payload.get("address") or "").strip()
                state = set_account_payout_enabled(
                    enhanced.admin.live.base.DB_PATH, address, enabled
                )
                return self.send_json({"ok": True, "address": address, "enabled": state})
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        if path == "/api/admin/users/mining":
            if not self._require_admin():
                return
            try:
                payload = self._read_json()
                suspended = payload.get("suspended")
                if not isinstance(suspended, bool):
                    return self.send_json({"error": "suspended must be true or false"}, 400)
                address = str(payload.get("address") or "").strip()
                state = set_account_suspended(
                    enhanced.admin.live.base.DB_PATH,
                    address,
                    suspended,
                    payload.get("reason") or "Admin suspension",
                )
                return self.send_json({"ok": True, "address": address, "suspended": state})
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        if path == "/api/admin/users/ip-ban":
            if not self._require_admin():
                return
            try:
                payload = self._read_json()
                banned = payload.get("banned")
                if not isinstance(banned, bool):
                    return self.send_json({"error": "banned must be true or false"}, 400)
                ip_address = str(payload.get("ip_address") or "").strip()
                state = set_ip_banned(
                    enhanced.admin.live.base.DB_PATH,
                    ip_address,
                    banned,
                    payload.get("reason") or "Admin pool ban",
                )
                return self.send_json({"ok": True, "ip_address": ip_address, "banned": state})
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
        return super().do_POST()


if __name__ == "__main__":
    ensure_user_control_schema(enhanced.admin.live.base.DB_PATH)
    print(
        f"YERB Pool web/admin listening on http://{enhanced.admin.live.base.HOST}:{enhanced.admin.live.base.PORT} "
        "(health diagnostics, payout controls and user controls enabled)"
    )
    ThreadingHTTPServer(
        (enhanced.admin.live.base.HOST, enhanced.admin.live.base.PORT), ControlHandler
    ).serve_forever()
