import asyncio
import logging
from decimal import Decimal

from yerbpool.database import COIN


class PayoutManager:
    def __init__(self, cfg, rpc, db):
        self.cfg = cfg
        self.rpc = rpc
        self.db = db
        pcfg = cfg.get("payouts", {})
        self.enabled = bool(pcfg.get("enabled", True))
        self.interval = max(10, int(pcfg.get("check_interval_seconds", 60)))
        self.maturity_confirmations = max(1, int(pcfg.get("coinbase_maturity", 100)))
        self.minimum_atomic = int(Decimal(str(pcfg.get("minimum_payout", "1.0"))) * COIN)
        self.pool_fee_percent = float(pcfg.get("pool_fee_percent", 0.0))

    async def start(self):
        asyncio.create_task(self._loop())

    async def _loop(self):
        while True:
            try:
                await self.process_blocks()
                if self.enabled:
                    await self.process_payouts()
            except Exception:
                logging.exception("Payout manager cycle failed")
            await asyncio.sleep(self.interval)

    async def process_blocks(self):
        for block in self.db.pending_blocks():
            try:
                info = await asyncio.to_thread(self.rpc.getblock, block["block_hash"])
            except Exception as exc:
                logging.warning("Block %s not queryable yet: %s", block["block_hash"], exc)
                continue

            confirmations = int(info.get("confirmations", 0)) if isinstance(info, dict) else 0
            if confirmations < 0:
                logging.warning("Block orphaned: %s", block["block_hash"])
                self.db.orphan_block(block["id"])
                continue

            self.db.update_block_confirmations(block["id"], confirmations)
            if confirmations >= self.maturity_confirmations:
                if self.db.mature_block(block["id"]):
                    logging.warning(
                        "BLOCK MATURE height=%s hash=%s confirmations=%s",
                        block.get("height"), block["block_hash"], confirmations,
                    )

    async def process_payouts(self):
        accounts = self.db.eligible_payout_accounts(self.minimum_atomic)
        if not accounts:
            return

        payout_id = self.db.create_payout(accounts)
        items = self.db.payout_items(payout_id)
        if not items:
            return

        amounts = {
            item["address"]: float(Decimal(item["amount_atomic"]) / Decimal(COIN))
            for item in items
        }
        total_atomic = sum(int(item["amount_atomic"]) for item in items)
        logging.info(
            "Sending payout batch id=%s recipients=%s total=%.8f YERB",
            payout_id, len(items), total_atomic / COIN,
        )

        # Lock these balances before talking to the wallet. If the RPC response
        # is lost after broadcast, the batch becomes 'uncertain' and is never
        # automatically paid a second time.
        self.db.mark_payout_broadcasting(payout_id)
        try:
            txid = await asyncio.to_thread(
                self.rpc.sendmany,
                amounts,
                f"YERB-Pool payout #{payout_id}",
            )
        except Exception as exc:
            self.db.mark_payout_uncertain(payout_id, exc)
            logging.exception(
                "Payout batch %s has uncertain broadcast state; manual reconciliation required",
                payout_id,
            )
            return

        self.db.mark_payout_sent(payout_id, str(txid))
        logging.warning("PAYOUT SENT id=%s txid=%s recipients=%s", payout_id, txid, len(items))
