#!/usr/bin/env python3
import asyncio
import logging

from yerbpool.config import load_config
from yerbpool.database import PoolDB
from yerbpool.ghostrider import ensure_available
from yerbpool.rpc import YerbasRPC
from yerbpool.jobs import JobManager
from yerbpool.stratum import StratumServer


async def main():
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.get("log_level", "INFO").upper()),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    ensure_available()
    logging.info("Native Yerbas GhostRider backend loaded")
    db = PoolDB(cfg["database"])
    rpc = YerbasRPC(cfg["rpc"])
    jobs = JobManager(rpc, cfg)
    server = StratumServer(cfg, rpc, jobs, db)
    await jobs.start()
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
