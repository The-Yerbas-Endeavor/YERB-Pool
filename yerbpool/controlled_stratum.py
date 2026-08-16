import asyncio
import logging

from yerbpool.stratum import MinerSession, StratumServer
from yerbpool.user_controls import is_ip_banned, record_worker_ip


def _peer_ip(writer):
    peer = writer.get_extra_info("peername")
    if isinstance(peer, (tuple, list)) and peer:
        return str(peer[0] or "")
    return ""


class ControlledMinerSession(MinerSession):
    def __init__(self, pool, reader, writer, peer_ip):
        super().__init__(pool, reader, writer)
        self.peer_ip = peer_ip

    async def handle(self, req):
        if self.peer_ip and is_ip_banned(self.pool.db, self.peer_ip):
            logging.warning("Blocked banned miner IP %s", self.peer_ip)
            await self.send({
                "id": req.get("id") if isinstance(req, dict) else None,
                "result": False,
                "error": [24, "IP address banned from pool", None],
            })
            self.writer.close()
            return

        method = req.get("method") if isinstance(req, dict) else None
        await super().handle(req)
        if method == "mining.authorize" and self.authorized and self.worker and self.peer_ip:
            try:
                record_worker_ip(self.pool.db, self.worker, self.peer_ip)
            except Exception:
                logging.exception(
                    "Failed to record miner IP worker=%s ip=%s", self.worker, self.peer_ip
                )


class ControlledStratumServer(StratumServer):
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
