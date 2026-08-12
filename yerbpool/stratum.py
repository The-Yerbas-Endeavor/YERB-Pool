import asyncio
import json
import logging
import os
from yerbpool.ghostrider import GhostRiderUnavailable, hash_header

class StratumServer:
    def __init__(self, cfg, rpc, jobs, db):
        self.cfg = cfg
        self.rpc = rpc
        self.jobs = jobs
        self.db = db
        self.difficulty = float(cfg["stratum"].get("difficulty", 0.01))

    async def serve(self):
        host = self.cfg["stratum"].get("host", "0.0.0.0")
        port = int(self.cfg["stratum"].get("port", 3333))
        server = await asyncio.start_server(self._client, host, port)
        logging.info("Stratum listening on %s:%s", host, port)
        async with server:
            await server.serve_forever()

    async def _client(self, reader, writer):
        session = MinerSession(self, reader, writer)
        self.jobs.register(session.send_job)
        try:
            await session.run()
        finally:
            self.jobs.unregister(session.send_job)
            writer.close()
            await writer.wait_closed()

class MinerSession:
    def __init__(self, pool, reader, writer):
        self.pool = pool
        self.reader = reader
        self.writer = writer
        self.worker = None
        self.authorized = False
        self.extranonce1 = os.urandom(4).hex()

    async def send(self, obj):
        self.writer.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        await self.writer.drain()

    async def run(self):
        while not self.reader.at_eof():
            line = await self.reader.readline()
            if not line:
                break
            try:
                req = json.loads(line.decode())
                await self.handle(req)
            except Exception as exc:
                logging.exception("Stratum request failed")
                await self.send({"id": None, "result": None, "error": [20, str(exc), None]})

    async def handle(self, req):
        method = req.get("method")
        rid = req.get("id")
        params = req.get("params") or []
        if method == "mining.subscribe":
            await self.send({"id": rid, "result": [[['mining.set_difficulty','1'],['mining.notify','1']], self.extranonce1, 4], "error": None})
            await self.send({"id": None, "method": "mining.set_difficulty", "params": [self.pool.difficulty]})
            await self.send_job(self.pool.jobs.snapshot(), True)
            return
        if method == "mining.authorize":
            self.worker = str(params[0]) if params else ""
            self.authorized = bool(self.worker and self.worker.split('.')[0] != "")
            await self.send({"id": rid, "result": self.authorized, "error": None})
            return
        if method == "mining.submit":
            await self.submit(rid, params)
            return
        await self.send({"id": rid, "result": None, "error": [20, "unsupported method", None]})

    async def send_job(self, job, clean):
        if not job:
            return
        tpl = job["template"]
        # This initial scaffold exposes the live template to connected miners,
        # but full coinbase/merkle Stratum job construction is completed next.
        params = [
            job["id"],
            tpl.get("previousblockhash", ""),
            "", "", [],
            f'{int(tpl.get("version", 0)) & 0xffffffff:08x}',
            tpl.get("bits", ""),
            f'{int(tpl.get("curtime", 0)) & 0xffffffff:08x}',
            bool(clean),
        ]
        await self.send({"id": None, "method": "mining.notify", "params": params})

    async def submit(self, rid, params):
        if not self.authorized:
            await self.send({"id": rid, "result": False, "error": [24, "unauthorized", None]})
            return
        job_id = str(params[1]) if len(params) > 1 else ""
        # A real submit must reconstruct the exact 80-byte header from the
        # Stratum job, extranonce, ntime and nonce. Until job construction is
        # complete, fail closed rather than credit unverifiable work.
        try:
            hash_header(b"\x00" * 80)
        except GhostRiderUnavailable as exc:
            self.pool.db.add_share(self.worker, job_id, self.pool.difficulty, False)
            await self.send({"id": rid, "result": False, "error": [20, str(exc), None]})
            return
        await self.send({"id": rid, "result": False, "error": [20, "share reconstruction not yet enabled", None]})
