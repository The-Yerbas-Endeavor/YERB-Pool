import asyncio
import logging
import time

from yerbpool.stratum import MinerSession, StratumServer
from yerbpool.user_controls import (
    is_account_suspended,
    is_ip_banned,
    record_worker_ip,
)


def _peer_ip(writer):
    peer = writer.get_extra_info("peername")
    if isinstance(peer, (tuple, list)) and peer:
        return str(peer[0] or "")
    return ""


class ControlledMinerSession(MinerSession):
    def __init__(self, pool, reader, writer, peer_ip):
        super().__init__(pool, reader, writer)
        self.peer_ip = peer_ip
        self.session_started_at = time.monotonic()
        self.last_idle_adjust_at = self.session_started_at

    def _worker_address(self, login=None):
        value = str(login if login is not None else self.worker or "")
        return self.pool.db.split_worker(value)[0] if value else ""

    async def _reject_suspended(self, rid):
        address = self._worker_address()
        logging.warning("Blocked suspended miner address %s ip=%s", address, self.peer_ip or "unknown")
        await self.send({
            "id": rid,
            "result": False,
            "error": [24, "Miner account suspended from pool", None],
        })
        self.writer.close()

    async def maybe_retarget(self):
        """Retarget VarDiff while preventing a single fast-share burst from overshooting."""
        if not self.pool.vardiff_enabled:
            return

        now = time.monotonic()
        if self.last_accepted_at is not None:
            interval = max(0.001, now - self.last_accepted_at)
            self.share_intervals.append(interval)
            if len(self.share_intervals) > 12:
                self.share_intervals.pop(0)
        self.last_accepted_at = now

        if now - self.last_retarget_at < self.pool.vardiff_retarget:
            return
        if len(self.share_intervals) < 2:
            return

        avg = sum(self.share_intervals) / len(self.share_intervals)
        lower = self.pool.vardiff_target * (1.0 - self.pool.vardiff_variance)
        upper = self.pool.vardiff_target * (1.0 + self.pool.vardiff_variance)
        if lower <= avg <= upper:
            self.last_retarget_at = now
            self.share_intervals.clear()
            return

        desired = self.difficulty * (self.pool.vardiff_target / avg)
        if desired > self.difficulty:
            desired = min(desired, self.difficulty * self.pool.vardiff_max_up_step)
        else:
            desired = max(desired, self.difficulty / self.pool.vardiff_max_step)

        self.last_retarget_at = now
        self.last_idle_adjust_at = now
        self.share_intervals.clear()
        await self.set_difficulty(desired, "share-rate", avg)

    async def vardiff_idle_loop(self):
        """Recover workers that stop finding shares after a VarDiff increase.

        Difficulty normally changes when a share arrives. That can strand a worker
        forever if an upward retarget overshoots badly enough that no more shares
        arrive. This loop steps difficulty down while the connection remains idle
        and sends a clean job so miners such as WildRig immediately adopt the new
        target.
        """
        try:
            while not self.reader.at_eof():
                await asyncio.sleep(self.pool.vardiff_idle_poll)
                if not self.pool.vardiff_enabled or not self.authorized or not self.subscribed:
                    continue

                now = time.monotonic()
                reference = self.last_accepted_at if self.last_accepted_at is not None else self.session_started_at
                idle_for = now - reference
                if idle_for < self.pool.vardiff_idle_timeout:
                    continue
                if now - self.last_idle_adjust_at < self.pool.vardiff_retarget:
                    continue
                if self.difficulty <= self.pool.vardiff_min:
                    self.last_idle_adjust_at = now
                    continue

                desired = max(
                    self.pool.vardiff_min,
                    self.difficulty / self.pool.vardiff_idle_step,
                )
                changed = await self.set_difficulty(
                    desired,
                    f"idle-recovery-{idle_for:.0f}s",
                )
                self.last_idle_adjust_at = now
                self.last_retarget_at = now
                self.share_intervals.clear()

                if changed:
                    job = self.pool.jobs.snapshot()
                    if job:
                        # A difficulty message alone is not enough for every miner.
                        # Send a clean notify so the lowered target takes effect now.
                        await self.send_job(job, True)
                    logging.warning(
                        "VarDiff idle recovery worker=%s idle=%.0fs diff=%.8g",
                        self.worker or "?",
                        idle_for,
                        self.difficulty,
                    )
        except asyncio.CancelledError:
            pass
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            logging.exception("VarDiff idle recovery loop failed worker=%s", self.worker or "?")

    async def handle(self, req):
        rid = req.get("id") if isinstance(req, dict) else None
        if self.peer_ip and is_ip_banned(self.pool.db, self.peer_ip):
            logging.warning("Blocked banned miner IP %s", self.peer_ip)
            await self.send({
                "id": rid,
                "result": False,
                "error": [24, "IP address banned from pool", None],
            })
            self.writer.close()
            return

        if self.worker and is_account_suspended(self.pool.db, self._worker_address()):
            await self._reject_suspended(rid)
            return

        method = req.get("method") if isinstance(req, dict) else None
        params = req.get("params") or [] if isinstance(req, dict) else []
        if method == "mining.authorize":
            login = str(params[0]) if params else ""
            address = self._worker_address(login)
            if address and is_account_suspended(self.pool.db, address):
                self.worker = login
                await self._reject_suspended(rid)
                return

        await super().handle(req)
        if method == "mining.authorize" and self.authorized and self.worker and self.peer_ip:
            try:
                record_worker_ip(self.pool.db, self.worker, self.peer_ip)
            except Exception:
                logging.exception(
                    "Failed to record miner IP worker=%s ip=%s", self.worker, self.peer_ip
                )


class ControlledStratumServer(StratumServer):
    def __init__(self, cfg, rpc, jobs, db, payouts=None):
        super().__init__(cfg, rpc, jobs, db, payouts)
        vardiff = cfg["stratum"].get("vardiff", {})
        self.vardiff_max_up_step = max(
            1.05, float(vardiff.get("max_up_step_factor", 1.5))
        )
        self.vardiff_idle_step = max(
            1.1, float(vardiff.get("idle_step_factor", self.vardiff_max_step))
        )
        default_idle_timeout = max(self.vardiff_retarget, self.vardiff_target * 4.0)
        self.vardiff_idle_timeout = max(
            self.vardiff_target * 2.0,
            float(vardiff.get("idle_timeout_seconds", default_idle_timeout)),
        )
        self.vardiff_idle_poll = max(
            5.0,
            min(
                self.vardiff_retarget,
                float(vardiff.get("idle_poll_seconds", self.vardiff_target)),
            ),
        )
        logging.info(
            "VarDiff safety up_step=%.3gx idle_timeout=%.1fs idle_step=%.3gx idle_poll=%.1fs",
            self.vardiff_max_up_step,
            self.vardiff_idle_timeout,
            self.vardiff_idle_step,
            self.vardiff_idle_poll,
        )

    async def _client(self, reader, writer):
        peer_ip = _peer_ip(writer)
        if peer_ip and is_ip_banned(self.db, peer_ip):
            logging.warning("Rejected connection from banned IP %s", peer_ip)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass
            return

        session = ControlledMinerSession(self, reader, writer, peer_ip)
        self.jobs.register(session.send_job)
        try:
            await session.run()
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            logging.info("Miner disconnected ip=%s", peer_ip or "unknown")
        finally:
            self.jobs.unregister(session.send_job)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass
