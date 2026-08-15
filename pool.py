#!/usr/bin/env python3
import asyncio
import json
import logging
import time
from pathlib import Path

from yerbpool.accounting import AccountingDB
from yerbpool.admin_settings import ensure_runtime_settings, ensure_treasury_address, sync_runtime_settings
from yerbpool.config import load_config
from yerbpool.fee_accounting import credit_pool_fee
from yerbpool.ghostrider import ensure_available
from yerbpool.jobs import JobManager
from yerbpool.payouts import PayoutManager
from yerbpool.rpc import YerbasRPC
from yerbpool.sqlite_safe import install_safe_sqlite_connections
from yerbpool.stratum import StratumServer


FORCE_PAYOUT_REQUEST = Path("runtime") / "force_payout_request.json"
FORCE_PAYOUT_RESULT = Path("runtime") / "force_payout_result.json"


def _write_force_result(payload):
    FORCE_PAYOUT_RESULT.parent.mkdir(parents=True, exist_ok=True)
    tmp = FORCE_PAYOUT_RESULT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(FORCE_PAYOUT_RESULT)


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

    jobs = JobManager(rpc, cfg)
    payouts = PayoutManager(cfg, rpc, db)

    # Scheduled and admin-forced payouts must never execute concurrently.
    payout_lock = asyncio.Lock()
    original_process_payouts = payouts.process_payouts

    async def serialized_process_payouts():
        async with payout_lock:
            return await original_process_payouts()

    payouts.process_payouts = serialized_process_payouts

    async def force_payout_loop():
        """Run authenticated admin payout requests through the normal payout engine."""
        while True:
            try:
                if FORCE_PAYOUT_REQUEST.exists():
                    try:
                        request = json.loads(FORCE_PAYOUT_REQUEST.read_text(encoding="utf-8"))
                    except Exception:
                        request = {}
                    try:
                        FORCE_PAYOUT_REQUEST.unlink()
                    except FileNotFoundError:
                        pass

                    request_id = str(request.get("request_id") or int(time.time()))
                    requested_at = int(request.get("requested_at") or time.time())
                    logging.warning("ADMIN FORCE PAYOUT requested id=%s", request_id)
                    try:
                        result = await payouts.process_payouts()
                        payload = {
                            "request_id": request_id,
                            "requested_at": requested_at,
                            "completed_at": int(time.time()),
                            "ok": True,
                            "result": result or "checked",
                        }
                        logging.warning("ADMIN FORCE PAYOUT completed id=%s result=%s", request_id, result)
                    except Exception as exc:
                        payload = {
                            "request_id": request_id,
                            "requested_at": requested_at,
                            "completed_at": int(time.time()),
                            "ok": False,
                            "result": "error",
                            "error": str(exc)[:300],
                        }
                        logging.exception("ADMIN FORCE PAYOUT failed id=%s", request_id)
                    _write_force_result(payload)
            except Exception:
                logging.exception("Force payout request loop failed")
            await asyncio.sleep(1)

    server = StratumServer(cfg, rpc, jobs, db, payouts)
    await jobs.start()
    await payouts.start()
    asyncio.create_task(force_payout_loop())
    asyncio.create_task(sync_runtime_settings(cfg))
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
