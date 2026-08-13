import asyncio
import logging
import threading
import time


def _template_signature(tpl):
    """Return the fields that actually change miner work.

    getblocktemplate commonly refreshes curtime on every poll. Sending a new
    Stratum job for that alone makes miners throw away useful nonce work. We
    only notify when the previous block, consensus/header fields, coinbase
    payments/payload, or transaction set changes.
    """
    transactions = tuple(
        (tx.get("hash"), tx.get("txid"), tx.get("data"))
        for tx in (tpl.get("transactions") or [])
    )
    smartnode = tuple(
        (item.get("amount"), item.get("script"))
        for item in (tpl.get("smartnode") or [])
    )
    superblock = tuple(
        (item.get("amount"), item.get("script"))
        for item in (tpl.get("superblock") or [])
    )
    founder = tpl.get("founder") or {}
    founder_sig = (founder.get("amount"), founder.get("script"))
    return (
        tpl.get("previousblockhash"),
        tpl.get("height"),
        tpl.get("version"),
        tpl.get("bits"),
        tpl.get("coinbasevalue"),
        tpl.get("coinbase_payload"),
        smartnode,
        superblock,
        founder_sig,
        transactions,
    )


class JobManager:
    def __init__(self, rpc, cfg):
        self.rpc = rpc
        self.cfg = cfg
        self.current = None
        self.jobs = {}
        self.lock = threading.Lock()
        self.listeners = set()
        self.counter = 0

    async def start(self):
        await self.refresh()
        asyncio.create_task(self._loop())

    async def _loop(self):
        delay = float(self.cfg.get("template_refresh_seconds", 5))
        while True:
            await asyncio.sleep(delay)
            try:
                await self.refresh()
            except Exception:
                logging.exception("Failed to refresh block template")

    async def refresh(self, force=False):
        tpl = await asyncio.to_thread(self.rpc.getblocktemplate)
        with self.lock:
            previous = self.current
            old_tpl = previous["template"] if previous else None
            old_sig = _template_signature(old_tpl) if old_tpl else None
            new_sig = _template_signature(tpl)

            if previous is not None and not force and new_sig == old_sig:
                # Keep the existing job. curtime-only GBT changes do not need
                # to reset every miner's nonce search.
                return previous

            old_prev = old_tpl.get("previousblockhash") if old_tpl else None
            self.counter += 1
            job = {"id": f"{int(time.time()):x}{self.counter:x}", "template": tpl}
            self.current = job
            self.jobs[job["id"]] = job
            while len(self.jobs) > 32:
                self.jobs.pop(next(iter(self.jobs)))
            clean = old_prev is not None and tpl.get("previousblockhash") != old_prev

        await self.notify(clean=clean)
        return job

    def snapshot(self):
        with self.lock:
            return self.current

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def register(self, callback):
        self.listeners.add(callback)

    def unregister(self, callback):
        self.listeners.discard(callback)

    async def notify(self, clean):
        for cb in tuple(self.listeners):
            try:
                await cb(self.snapshot(), clean)
            except Exception:
                logging.exception("Failed to notify miner of new job")
