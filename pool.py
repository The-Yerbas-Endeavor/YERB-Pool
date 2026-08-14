#!/usr/bin/env python3
import asyncio
import logging

from yerbpool.accounting import AccountingDB
from yerbpool.config import load_config
from yerbpool.ghostrider import ensure_available
from yerbpool.jobs import JobManager
from yerbpool.payouts import PayoutManager
from yerbpool.rpc import YerbasRPC
from yerbpool.sqlite_safe import install_safe_sqlite_connections
from yerbpool.stratum import StratumServer


async def main():
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.get("log_level", "INFO").upper()),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    install_safe_sqlite_connections()
    ensure_available()
    logging.info("Native Yerbas GhostRider backend loaded")
    logging.info("Safe SQLite connection cleanup enabled")
    db = AccountingDB(cfg["database"])
    rpc = YerbasRPC(cfg["rpc"])
    jobs = JobManager(rpc, cfg)
    payouts = PayoutManager(cfg, rpc, db)
    server = StratumServer(cfg, rpc, jobs, db, payouts)
    await jobs.start()
    await payouts.start()
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
