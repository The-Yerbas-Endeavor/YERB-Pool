import asyncio
import json
import logging
import os
import time

from yerbpool.block import (
    block_bytes,
    coinbase_merkle_branch,
    coinbase_parts,
    compact_target,
    header_bytes,
    merkle_root_from_coinbase,
    share_target,
    sha256d,
    stratum_prevhash,
    template_outputs,
)
from yerbpool.ghostrider import hash_header
from yerbpool.rejections import ensure_rejection_schema, record_rejection


def _fixed_hex(value, size):
    value = str(value).lower()
    if len(value) != size * 2 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"expected {size}-byte hex value")
    return value


class StratumServer:
    def __init__(self, cfg, rpc, jobs, db, payouts=None):
        self.cfg = cfg
        self.rpc = rpc
        self.jobs = jobs
        self.db = db
        self.payouts = payouts
        ensure_rejection_schema(self.db)
        self.difficulty = float(cfg["stratum"].get("difficulty", 0.05))
        vardiff = cfg["stratum"].get("vardiff", {})
        self.vardiff_enabled = bool(vardiff.get("enabled", False))
        self.vardiff_min = float(vardiff.get("min_difficulty", self.difficulty))
        self.vardiff_max = float(vardiff.get("max_difficulty", max(self.difficulty, 65536.0)))
        self.vardiff_target = max(1.0, float(vardiff.get("target_share_seconds", 12)))
        self.vardiff_retarget = max(10.0, float(vardiff.get("retarget_seconds", 60)))
        self.vardiff_variance = max(0.0, min(0.95, float(vardiff.get("variance_percent", 30)) / 100.0))
        self.vardiff_max_step = max(1.1, float(vardiff.get("max_step_factor", 2.0)))
        self.pool_address = cfg["pool_address"]

    async def serve(self):
        host = self.cfg["stratum"].get("host", "0.0.0.0")
        port = int(self.cfg["stratum"].get("port", 3333))
        server = await asyncio.start_server(self._client, host, port)
        logging.info(
            "Stratum listening on %s:%s diff=%s vardiff=%s target=%ss range=%s-%s",
            host, port, self.difficulty, self.vardiff_enabled,
            self.vardiff_target, self.vardiff_min, self.vardiff_max,
        )
        async with server:
            await server.serve_forever()

    async def _client(self, reader, writer):
        session = MinerSession(self, reader, writer)
        self.jobs.register(session.send_job)
        try:
            await session.run()
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            logging.info("Miner disconnected")
        finally:
            self.jobs.unregister(session.send_job)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass


class MinerSession:
    extranonce2_size = 4

    def __init__(self, pool, reader, writer):
        self.pool = pool
        self.reader = reader
        self.writer = writer
        self.worker = None
        self.authorized = False
        self.subscribed = False
        self.extranonce_subscribed = False
        self.extranonce1 = os.urandom(4).hex()
        self.seen = set()
        self.difficulty = min(max(pool.difficulty, pool.vardiff_min), pool.vardiff_max)
        now = time.monotonic()
        self.last_accepted_at = None
        self.last_retarget_at = now
        self.share_intervals = []
        self.vardiff_task = None

    async def send(self, obj):
        self.writer.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        await self.writer.drain()

    def record_reject(self, reason, job_id="", hash_hex=None):
        if not self.authorized or not self.worker:
            return None
        try:
            return record_rejection(
                self.pool.db,
                self.worker,
                job_id,
                self.difficulty,
                reason,
                hash_hex,
            )
        except Exception:
            logging.exception(
                "Failed to persist rejected share worker=%s job=%s reason=%s",
                self.worker,
                job_id,
                reason,
            )
            return None

    async def send_difficulty(self):
        await self.send({"id": None, "method": "mining.set_difficulty",
                         "params": [self.difficulty]})

    async def set_difficulty(self, desired, reason, avg=None):
        desired = min(max(float(desired), self.pool.vardiff_min), self.pool.vardiff_max)
        desired = float(f"{desired:.12g}")
        if abs(desired - self.difficulty) <= max(1e-12, self.difficulty * 0.01):
            return False
        old = self.difficulty
        self.difficulty = desired
        logging.info(
            "VarDiff worker=%s %.8g -> %.8g reason=%s%s",
            self.worker or "?", old, self.difficulty, reason,
            "" if avg is None else f" avg_share={avg:.2f}s target={self.pool.vardiff_target:.2f}s",
        )
        await self.send_difficulty()
        return True

    async def maybe_retarget(self):
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
        lo = self.difficulty / self.pool.vardiff_max_step
        hi = self.difficulty * self.pool.vardiff_max_step
        desired = min(max(desired, lo), hi)

        self.last_retarget_at = now
        self.share_intervals.clear()
        await self.set_difficulty(desired, "share-rate", avg)

    async def vardiff_idle_loop(self):
        try:
            while not self.reader.at_eof():
                await asyncio.sleep(self.pool.vardiff_retarget)
                if not self.pool.vardiff_enabled or not self.authorized or not self.subscribed:
                    continue
                now = time.monotonic()
                reference = self.last_accepted_at if self.last_accepted_at is not None else self.last_retarget_at
                if now - reference < self.pool.vardiff_retarget:
                    continue
                if self.difficulty <= self.pool.vardiff_min:
                    self.last_retarget_at = now
                    continue
                desired = max(self.pool.vardiff_min, self.difficulty / self.pool.vardiff_max_step)
                changed = await self.set_difficulty(desired, "idle-no-accepted-shares")
                self.last_retarget_at = now
                self.share_intervals.clear()
                if changed:
                    self.last_accepted_at = None
        except asyncio.CancelledError:
            pass
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            logging.exception("VarDiff idle loop failed worker=%s", self.worker or "?")

    async def run(self):
        if self.pool.vardiff_enabled:
            self.vardiff_task = asyncio.create_task(self.vardiff_idle_loop())
        try:
            while not self.reader.at_eof():
                req = None
                line = await self.reader.readline()
                if not line:
                    break
                try:
                    req = json.loads(line.decode())
                    await self.handle(req)
                except Exception as exc:
                    logging.exception("Stratum request failed")
                    await self.send({"id": req.get("id") if isinstance(req, dict) else None,
                                     "result": None, "error": [20, str(exc), None]})
        finally:
            if self.vardiff_task is not None:
                self.vardiff_task.cancel()
                try:
                    await self.vardiff_task
                except asyncio.CancelledError:
                    pass

    async def handle(self, req):
        method = req.get("method")
        rid = req.get("id")
        params = req.get("params") or []

        if method == "mining.subscribe":
            self.subscribed = True
            await self.send({
                "id": rid,
                "result": [[["mining.set_difficulty", "1"], ["mining.notify", "1"]],
                           self.extranonce1, self.extranonce2_size],
                "error": None,
            })
            await self.send_difficulty()
            await self.send_job(self.pool.jobs.snapshot(), True)
            return

        if method == "mining.authorize":
            self.worker = str(params[0]) if params else ""
            self.authorized = bool(self.worker and self.worker.split(".")[0])
            if self.authorized:
                self.pool.db.get_or_create_worker(self.worker)
            await self.send({"id": rid, "result": self.authorized, "error": None})
            return

        if method == "mining.extranonce.subscribe":
            self.extranonce_subscribed = True
            await self.send({"id": rid, "result": True, "error": None})
            return

        if method == "mining.submit":
            await self.submit(rid, params)
            return

        await self.send({"id": rid, "result": None,
                         "error": [20, "unsupported method", None]})

    async def send_job(self, job, clean):
        if not job or not self.subscribed:
            return
        tpl = job["template"]
        coinb1, coinb2 = coinbase_parts(
            tpl, self.pool.pool_address, len(bytes.fromhex(self.extranonce1)),
            self.extranonce2_size,
        )
        branch = coinbase_merkle_branch(tpl)
        params = [
            job["id"],
            stratum_prevhash(tpl["previousblockhash"]),
            coinb1.hex(),
            coinb2.hex(),
            [item.hex() for item in branch],
            f'{int(tpl["version"]) & 0xffffffff:08x}',
            tpl["bits"],
            f'{int(tpl["curtime"]) & 0xffffffff:08x}',
            bool(clean),
        ]
        await self.send({"id": None, "method": "mining.notify", "params": params})

    async def submit(self, rid, params):
        if not self.authorized:
            await self.send({"id": rid, "result": False,
                             "error": [24, "unauthorized", None]})
            return
        if len(params) < 5:
            self.record_reject("invalid mining.submit", params[1] if len(params) > 1 else "")
            await self.send({"id": rid, "result": False,
                             "error": [20, "invalid mining.submit", None]})
            return

        worker, job_id, extranonce2, ntime_hex, nonce_hex = map(str, params[:5])
        if worker != self.worker:
            self.record_reject("worker mismatch", job_id)
            await self.send({"id": rid, "result": False,
                             "error": [24, "worker mismatch", None]})
            return

        job = self.pool.jobs.get(job_id)
        current = self.pool.jobs.snapshot()
        if (not job or not current or
                job["template"].get("previousblockhash") !=
                current["template"].get("previousblockhash")):
            self.record_reject("stale job", job_id)
            await self.send({"id": rid, "result": False,
                             "error": [21, "stale job", None]})
            return

        try:
            extranonce2 = _fixed_hex(extranonce2, self.extranonce2_size)
            ntime_hex = _fixed_hex(ntime_hex, 4)
            nonce_hex = _fixed_hex(nonce_hex, 4)
        except ValueError as exc:
            self.record_reject(str(exc), job_id)
            await self.send({"id": rid, "result": False,
                             "error": [20, str(exc), None]})
            return

        duplicate_key = (job_id, extranonce2, ntime_hex, nonce_hex)
        if duplicate_key in self.seen:
            self.record_reject("duplicate share", job_id)
            await self.send({"id": rid, "result": False,
                             "error": [22, "duplicate share", None]})
            return
        self.seen.add(duplicate_key)

        tpl = job["template"]
        ntime = int(ntime_hex, 16)
        if ntime < int(tpl.get("mintime", 0)):
            self.record_reject("ntime below mintime", job_id)
            await self.send({"id": rid, "result": False,
                             "error": [20, "ntime below mintime", None]})
            return

        coinb1, coinb2 = coinbase_parts(
            tpl, self.pool.pool_address, len(bytes.fromhex(self.extranonce1)),
            self.extranonce2_size,
        )
        coinbase = coinb1 + bytes.fromhex(self.extranonce1 + extranonce2) + coinb2
        branch = coinbase_merkle_branch(tpl)
        merkle = merkle_root_from_coinbase(coinbase, branch)
        header = header_bytes(tpl, merkle, ntime_hex, nonce_hex)
        pow_hash = await asyncio.to_thread(hash_header, header)
        hash_value = int.from_bytes(pow_hash, "little")

        share_diff = self.difficulty
        s_target = share_target(share_diff)
        target_hex = tpl.get("target")
        network_target = int(target_hex, 16) if isinstance(target_hex, str) and target_hex else compact_target(tpl["bits"])

        if hash_value > s_target:
            reject_hash = pow_hash[::-1].hex()
            self.record_reject("low difficulty share", job_id, reject_hash)
            await self.send({"id": rid, "result": False,
                             "error": [23, "low difficulty share", None]})
            return

        is_block = hash_value <= network_target
        share_id = self.pool.db.add_share(self.worker, job_id, share_diff, True,
                                          is_block, pow_hash[::-1].hex())

        if is_block:
            raw_block = block_bytes(header, coinbase, tpl)
            result = await asyncio.to_thread(self.pool.rpc.submitblock, raw_block.hex())
            if result is not None:
                logging.error("submitblock rejected candidate job=%s result=%r",
                              job_id, result)
                await self.send({"id": rid, "result": False,
                                 "error": [20, f"submitblock: {result}", None]})
                return

            block_hash = sha256d(header)[::-1].hex()
            height = int(tpl.get("height", 0))
            pool_reward = int(template_outputs(tpl, self.pool.pool_address)[0][0])
            network_reward = int(tpl.get("coinbasevalue", pool_reward))
            maturity = int(self.pool.cfg.get("payouts", {}).get("coinbase_maturity", 100))
            block_id = self.pool.db.record_block(
                self.worker, job_id, block_hash, height, pool_reward, network_reward,
                share_id, height + maturity,
            )
            pool_fee = float(self.pool.cfg.get("payouts", {}).get("pool_fee_percent", 0.0))
            self.pool.db.allocate_block_immature(block_id, pool_fee)

            logging.warning("BLOCK ACCEPTED worker=%s job=%s hash=%s",
                            self.worker, job_id, block_hash)
            try:
                await self.pool.jobs.refresh(force=True)
            except TypeError:
                await self.pool.jobs.refresh()
            except Exception:
                logging.exception("Failed to refresh after accepted block")

        await self.send({"id": rid, "result": True, "error": None})
        await self.maybe_retarget()