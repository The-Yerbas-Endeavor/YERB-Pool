#!/usr/bin/env python3
import asyncio
import logging

from yerbpool.accounting import AccountingDB
from yerbpool.admin_settings import ensure_runtime_settings, sync_runtime_settings
from yerbpool.config import load_config
from yerbpool.fee_accounting import credit_pool_fee
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
    ensure_available()
    logging.info("Native Yerbas GhostRider backend loaded")
    install_safe_sqlite_connections()
    logging.info("Safe SQLite connection cleanup enabled")
    db = AccountingDB(cfg["database"])
    ensure_runtime_settings(cfg)
    logging.info("Current pool fee %.4f%%", float(cfg.get("payouts", {}).get("pool_fee_percent", 0.0)))
    if cfg.get("payouts", {}).get("pool_fee_address"):
        logging.info("Pool fee address %s", cfg["payouts"]["pool_fee_address"])

    # Stratum already calls db.allocate_block_immature(block_id, fee_percent).
    # Wrap that instance method so the existing miner allocation remains
    # unchanged and the recorded fee is also credited to the configured fee
    # address through the normal immature -> mature -> payout accounting path.
    original_allocate_block_immature = db.allocate_block_immature

    def allocate_block_immature_with_fee(block_id, pool_fee_percent=0.0):
        original_allocate_block_immature(block_id, pool_fee_percent)
        credit_pool_fee(
            db,
            block_id,
            cfg.get("payouts", {}).get("pool_fee_address", ""),
        )

    db.allocate_block_immature = allocate_block_immature_with_fee

    rpc = YerbasRPC(cfg["rpc"])
    jobs = JobManager(rpc, cfg)
    payouts = PayoutManager(cfg, rpc, db)
    server = StratumServer(cfg, rpc, jobs, db, payouts)
    await jobs.start()
    await payouts.start()
    asyncio.create_task(sync_runtime_settings(cfg))
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
