#!/usr/bin/env python3
"""Production web entry point with authenticated payout and user controls."""

import sqlite3
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

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


def _ensure_chart_index():
    """Install a covering index used by pool-wide historical hashrate queries."""
    path = enhanced.admin.live.base.DB_PATH
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_shares_ts_accepted_diff "
            "ON shares(ts, accepted, difficulty)"
        )
        con.commit()
    finally:
        con.close()


def _hashrate_chart_snapshot(hours=24, bucket=600):
    """Return the canonical enhanced dashboard chart payload."""
    hours = min(max(int(hours), 1), 168)
    bucket = min(max(int(bucket), 60), 3600)
    return enhanced.admin.live.api_hashrate_chart(hours, bucket)


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
    with enhanced.admin.live.base.db() as con:
        for user in users:
            user["workers"] = enhanced.admin.live.base.rows(
                con,
                "SELECT id,name FROM workers WHERE account_id=? ORDER BY name",
                (int(user["id"]),),
            )
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
#admin-users{margin-top:14px}.user-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}.user-toolbar input{width:min(520px,80vw)}.admin-user-cards{display:grid;gap:14px}.admin-user-card{border:1px solid #303830;border-radius:11px;background:#151a16;padding:16px}.admin-user-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap}.admin-user-title code{font-size:13px;word-break:break-all}.admin-user-status,.admin-user-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.admin-user-metrics{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:8px;margin:14px 0}.admin-user-metric{border:1px solid #2d4332;border-radius:8px;background:#111612;padding:10px 11px;min-width:0}.admin-user-metric span,.admin-user-metric small{display:block;color:#91a394;font-size:10px}.admin-user-metric strong{display:block;color:#e7f4e8;font-size:16px;margin:3px 0;overflow-wrap:anywhere}.admin-user-actions{padding-top:2px}.admin-user-download{margin-left:auto}.admin-user-details{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:14px}.admin-user-details details{border:1px solid #2b342d;border-radius:8px;background:#111412;padding:0 11px}.admin-user-details summary{cursor:pointer;padding:10px 0;font-weight:700;color:#c9d9cb}.admin-user-details summary span{float:right;color:#8fa192}.admin-user-details details[open] summary{border-bottom:1px solid #293129;margin-bottom:9px}.admin-user-details dl{margin:0 0 10px}.admin-user-details dl div{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-bottom:1px solid #222a23}.admin-user-details dt{color:#91a394}.admin-user-details dd{margin:0;text-align:right}.admin-worker-list>div{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-bottom:1px solid #222a23}.user-export-link{font-size:11px;white-space:nowrap}.user-empty-detail{padding:5px 0 11px}.user-small{font-size:11px;margin-top:4px}.admin-ip{position:relative;padding:7px 90px 8px 0;border-bottom:1px solid #222a23}.admin-ip .user-mini-btn{position:absolute;right:0;top:7px}.user-badge{display:inline-block;padding:3px 7px;border-radius:999px;border:1px solid #444;font-size:11px;font-weight:700}.user-ok{color:#9fe3a7;border-color:#376c41;background:#152719}.user-paused{color:#ffe08a;border-color:#6d5d2b;background:#29240f}.user-banned,.user-suspended{color:#ffaaaa;border-color:#7b3737;background:#2b1515}.user-control-btn,.user-mini-btn{padding:6px 9px;font-size:11px}.danger{background:#8a3434}button:disabled{opacity:.55;cursor:wait}@media(max-width:1000px){.admin-user-metrics{grid-template-columns:repeat(2,minmax(130px,1fr))}.admin-user-details{grid-template-columns:1fr}}@media(max-width:560px){.admin-user-card{padding:12px}.admin-user-metrics{grid-template-columns:1fr 1fr}.admin-user-download{width:100%;margin-left:0}.admin-user-status{width:100%}}@media(max-width:390px){.admin-user-metrics{grid-template-columns:1fr}}
</style><script src="/admin_users.js?v=4"></script>'''
        html = html.replace("</body>", extra + "</body>")
    if 'id="admin-access-users"' not in html:
        access_section = (
            '<section id="admin-access-users"><div><h2 style="margin-bottom:4px">Admin access</h2>'
            '<div class="muted">Add or manage people who can sign in to this Admin panel.</div></div>'
            '<div id="admin-access-content" style="margin-top:14px"><div class="admin-card">Loading administrators…</div></div></section>'
        )
        html = html.replace('<section><h2>Payout configuration</h2>', access_section + '<section><h2>Payout configuration</h2>')
    if "/admin_access.js" not in html:
        html = html.replace("</body>", '<script src="/admin_access.js?v=1"></script></body>')
    return html


class ControlHandler(enhanced.EnhancedHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/api/hashrate/chart":
            query = parse_qs(parsed.query)
            try:
                return self.send_json(
                    _hashrate_chart_snapshot(
                        (query.get("hours") or [24])[0],
                        (query.get("bucket") or [600])[0],
                    )
                )
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
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
        if path == "/api/admin/access/users":
            identity = self._admin_identity()
            if not identity:
                self._require_admin()
                return
            return self.send_json({
                "current_user": identity.get("username"),
                "can_manage": identity.get("role") == "owner",
                "users": enhanced.admin.list_admin_users() if identity.get("role") == "owner" else [],
            })
        if path.startswith("/api/admin/export/account/") and path.endswith(".csv"):
            if not self._require_admin():
                return
            address = unquote(path[len("/api/admin/export/account/"):-4])
            body = enhanced.detail_data_csv("account", address, days=None, include_sensitive=True)
            if body is None:
                return self.send_json({"error": "account not found"}, 404)
            return self.send_csv(body, f"yerb-admin-account-lifetime-{enhanced.time.strftime('%Y-%m-%d')}.csv")
        if path.startswith("/api/admin/export/worker/") and path.endswith(".csv"):
            if not self._require_admin():
                return
            worker_id = unquote(path[len("/api/admin/export/worker/"):-4])
            body = enhanced.detail_data_csv("worker", worker_id, days=None, include_sensitive=True)
            if body is None:
                return self.send_json({"error": "worker not found"}, 404)
            return self.send_csv(body, f"yerb-admin-worker-{worker_id}-lifetime-{enhanced.time.strftime('%Y-%m-%d')}.csv")
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/admin/access/users":
            if not self._require_owner():
                return
            try:
                payload = self._read_json()
                action = str(payload.get("action") or "add")
                username = payload.get("username")
                if action == "add":
                    enhanced.admin.add_admin_user(username, payload.get("password"))
                elif action == "password":
                    enhanced.admin.update_admin_user(username, password=payload.get("password"))
                elif action == "enabled":
                    enhanced.admin.update_admin_user(username, enabled=bool(payload.get("enabled")))
                elif action == "delete":
                    enhanced.admin.update_admin_user(username, delete=True)
                else:
                    raise ValueError("Unknown administrator action")
                return self.send_json({"ok": True, "username": username})
            except (ValueError, TypeError) as exc:
                return self.send_json({"error": str(exc)}, 400)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)
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
    _ensure_chart_index()
    print(
        f"YERB Pool web/admin listening on http://{enhanced.admin.live.base.HOST}:{enhanced.admin.live.base.PORT} "
        "(health diagnostics, payout controls and user controls enabled)"
    )
    ThreadingHTTPServer(
        (enhanced.admin.live.base.HOST, enhanced.admin.live.base.PORT), ControlHandler
    ).serve_forever()
