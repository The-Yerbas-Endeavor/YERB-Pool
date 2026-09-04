#!/usr/bin/env python3
import asyncio
import logging

from yerbpool.accounting import AccountingDB
from yerbpool.admin_settings import ensure_runtime_settings, ensure_treasury_address, sync_runtime_settings
from yerbpool.config import load_config
from yerbpool.controlled_stratum import ControlledStratumServer
from yerbpool.fee_accounting import credit_pool_fee
from yerbpool.ghostrider import ensure_available
from yerbpool.jobs import JobManager
from yerbpool.payouts import PayoutManager
from yerbpool.rpc import YerbasRPC
from yerbpool.sqlite_safe import install_safe_sqlite_connections


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
    rpc = YerbasRPC(cfg["rpc"])
    treasury_address = ensure_treasury_address(cfg, rpc)
    logging.info("Current pool fee %.4f%%", float(cfg.get("payouts", {}).get("pool_fee_percent", 0.0)))
    logging.info("Pool treasury address %s", treasury_address)

    original_allocate_block_immature = db.allocate_block_immature

    def allocate_block_immature_with_fee(block_id, pool_fee_percent=0.0):
        original_allocate_block_immature(block_id, pool_fee_percent)
        credit_pool_fee(db, block_id, treasury_address)

    db.allocate_block_immature = allocate_block_immature_with_fee

    # Defensive payout filtering: only valid Yerbas addresses may enter a payout
    # record. This keeps one malformed/legacy account from poisoning sendmany and
    # keeps payout_items consistent with the recipients that are actually sent.
    original_eligible_payout_accounts = db.eligible_payout_accounts

    def eligible_validated_payout_accounts(default_minimum_atomic):
        accounts = original_eligible_payout_accounts(default_minimum_atomic)
        valid = []
        for account in accounts:
            address = str(account.get("address") or "").strip()
            if not address or address.lower().startswith("solo:"):
                logging.error(
                    "Skipping invalid payout account id=%s address=%r",
                    account.get("id"),
                    address,
                )
                continue
            try:
                info = rpc.validateaddress(address)
            except Exception:
                logging.exception(
                    "Unable to validate payout address id=%s address=%s",
                    account.get("id"),
                    address,
                )
                raise
            if not isinstance(info, dict) or not bool(info.get("isvalid")):
                logging.error(
                    "Skipping invalid Yerbas payout address id=%s address=%s",
                    account.get("id"),
                    address,
                )
                continue
            valid.append(account)
        return valid

    db.eligible_payout_accounts = eligible_validated_payout_accounts

    jobs = JobManager(rpc, cfg)
    payouts = PayoutManager(cfg, rpc, db)
    server = ControlledStratumServer(cfg, rpc, jobs, db, payouts)
    await jobs.start()
    await payouts.start()
    asyncio.create_task(sync_runtime_settings(cfg))
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
