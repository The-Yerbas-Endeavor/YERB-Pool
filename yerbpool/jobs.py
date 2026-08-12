import asyncio
import logging
import threading
import time

class JobManager:
    def __init__(self, rpc, cfg):
        self.rpc = rpc
        self.cfg = cfg
        self.current = None
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

    async def refresh(self):
        tpl = await asyncio.to_thread(self.rpc.getblocktemplate)
        with self.lock:
            old_prev = self.current["template"].get("previousblockhash") if self.current else None
            self.counter += 1
            self.current = {"id": f"{int(time.time()):x}{self.counter:x}", "template": tpl}
            changed = tpl.get("previousblockhash") != old_prev
        if changed:
            await self.notify()
        return self.current

    def snapshot(self):
        with self.lock:
            return self.current

    def register(self, callback):
        self.listeners.add(callback)

    def unregister(self, callback):
        self.listeners.discard(callback)

    async def notify(self):
        for cb in tuple(self.listeners):
            try:
                await cb(self.snapshot(), True)
            except Exception:
                logging.exception("Failed to notify miner of new job")
