import asyncio
import json
import logging
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from yerbpool.database import COIN
from yerbpool.payout_control import consume_request, finish_request, read_control


class PayoutManager:
    def __init__(self, cfg, rpc, db):
        self.cfg = cfg
        self.rpc = rpc
        self.db = db
        pcfg = cfg.get("payouts", {})
        self.enabled = bool(pcfg.get("enabled", True))

        # Block confirmation/maturity tracking must remain frequent, while
        # actual miner payments are intentionally batched every two hours.
        self.block_check_interval = max(10, int(pcfg.get("block_check_interval_seconds", 60)))
        configured_payout_interval = int(pcfg.get("check_interval_seconds", 7200))
        # Migrate the original 60-second default automatically on existing installs.
        if configured_payout_interval == 60:
            configured_payout_interval = 7200
        self.payout_interval = max(10, configured_payout_interval)

        self.maturity_confirmations = max(1, int(pcfg.get("coinbase_maturity", 100)))
        self.minimum_atomic = int(Decimal(str(pcfg.get("minimum_payout", "1.0"))) * COIN)
        self.pool_fee_percent = float(pcfg.get("pool_fee_percent", 0.0))
        self.fee_reserve_atomic = max(
            0,
            int(Decimal(str(pcfg.get("transaction_fee_reserve", "0.01"))) * COIN),
        )
        self.pool_address = str(cfg.get("pool_address", ""))
        self.payout_account = pcfg.get("account")

        # This file contains public scheduler metadata only. It is intentionally
        # separate from accounting state so dashboard transparency cannot alter
        # balances or payout records.
        self.status_path = Path("web") / "payout_status.json"
        self.next_payout_check_at = 0
        self.last_payout_check_at = 0
        self.last_payout_result = "waiting"
        self.paused = bool(read_control().get("paused", False))
        self._payout_lock = asyncio.Lock()

    def _write_status(self, **extra):
        """Atomically publish read-only payout scheduler state for the dashboard."""
        data = {
            "enabled": self.enabled,
            "paused": self.paused,
            "interval_seconds": self.payout_interval,
            "minimum_payout_atomic": self.minimum_atomic,
            "next_check_at": int(self.next_payout_check_at or 0),
            "last_check_at": int(self.last_payout_check_at or 0),
            "last_result": self.last_payout_result,
        }
        data.update(extra)
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.status_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
            tmp.replace(self.status_path)
        except Exception:
            logging.exception("Unable to publish payout scheduler status")

    async def start(self):
        logging.info(
            "Payout scheduler enabled=%s paused=%s interval=%ss block_check=%ss",
            self.enabled,
            self.paused,
            self.payout_interval,
            self.block_check_interval,
        )
        asyncio.create_task(self._block_loop())
        asyncio.create_task(self._control_loop())
        if self.enabled:
            self.next_payout_check_at = int(time.time()) + self.payout_interval
            self._write_status()
            asyncio.create_task(self._payout_loop())
        else:
            self._write_status()

    async def _block_loop(self):
        while True:
            try:
                await self.process_blocks()
            except Exception:
                logging.exception("Block maturity cycle failed")
            await asyncio.sleep(self.block_check_interval)

    async def _run_payout_check(self, source="scheduled"):
        async with self._payout_lock:
            self.last_payout_check_at = int(time.time())
            if self.paused:
                self.last_payout_result = "paused"
                self._write_status(last_source=source)
                return "paused"
            try:
                result = await self.process_payouts()
                self.last_payout_result = result or "checked"
                return self.last_payout_result
            except Exception:
                self.last_payout_result = "error"
                logging.exception("Payout cycle failed source=%s", source)
                raise
            finally:
                self._write_status(last_source=source)

    async def _payout_loop(self):
        # Wait one full payout interval before the first scheduled batch after
        # service startup. This prevents a restart from causing an immediate
        # unscheduled payment.
        while True:
            delay = max(1, int(self.next_payout_check_at - time.time()))
            await asyncio.sleep(delay)
            try:
                await self._run_payout_check("scheduled")
            except Exception:
                pass
            finally:
                self.next_payout_check_at = int(time.time()) + self.payout_interval
                self._write_status()

    async def _control_loop(self):
        """Apply runtime pause state and consume authenticated admin requests."""
        while True:
            try:
                control = read_control()
                paused = bool(control.get("paused", False))
                if paused != self.paused:
                    self.paused = paused
                    logging.warning("ADMIN PAYOUTS %s", "PAUSED" if paused else "RESUMED")
                    self._write_status()

                request = consume_request()
                if request:
                    request_id = str(request.get("request_id") or "unknown")
                    requested_at = int(request.get("requested_at") or time.time())
                    if self.paused:
                        result = "paused"
                        ok = False
                        error = "Payouts are paused"
                    elif not self.enabled:
                        result = "disabled"
                        ok = False
                        error = "Payout scheduler is disabled"
                    else:
                        logging.warning("ADMIN PAYOUT CHECK requested id=%s", request_id)
                        try:
                            result = await self._run_payout_check("admin")
                            ok = result != "paused"
                            error = None
                        except Exception as exc:
                            result = "error"
                            ok = False
                            error = str(exc)[:300]
                    payload = {
                        "request_id": request_id,
                        "requested_at": requested_at,
                        "completed_at": int(time.time()),
                        "ok": ok,
                        "result": result,
                    }
                    if error:
                        payload["error"] = error
                    finish_request(payload)
                    logging.warning("ADMIN PAYOUT CHECK completed id=%s result=%s", request_id, result)
            except Exception:
                logging.exception("Payout control loop failed")
            await asyncio.sleep(1)

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

            self.db.update_block_confirmations(
                block["id"], confirmations, self.maturity_confirmations
            )
            if confirmations >= self.maturity_confirmations:
                if self.db.mature_block(block["id"]):
                    logging.warning(
                        "BLOCK MATURE height=%s hash=%s confirmations=%s",
                        block.get("height"), block["block_hash"], confirmations,
                    )

    async def _resolve_payout_account(self):
        if self.payout_account is not None:
            return str(self.payout_account)
        if not self.pool_address:
            raise RuntimeError("pool_address is not configured")
        account = await asyncio.to_thread(self.rpc.getaccount, self.pool_address)
        self.payout_account = str(account)
        logging.info(
            "Using Yerbas wallet account %r for pool address %s",
            self.payout_account,
            self.pool_address,
        )
        return self.payout_account

    def _cap_accounts_to_wallet(self, accounts, wallet_atomic):
        """Cap a payout batch to spendable wallet-account funds minus a fee reserve.

        The reduction is proportional across eligible accounts so no one miner
        absorbs the whole transaction-fee reserve. Any unpaid remainder stays in
        account.balance_atomic and is eligible on a later payout cycle.
        """
        available = max(0, int(wallet_atomic) - self.fee_reserve_atomic)
        total_due = sum(max(0, int(a.get("balance_atomic", 0))) for a in accounts)
        if available <= 0 or total_due <= 0:
            return []
        if total_due <= available:
            return [dict(a) for a in accounts]

        ratio = Decimal(available) / Decimal(total_due)
        capped = []
        used = 0
        fractions = []
        for index, account in enumerate(accounts):
            due = max(0, int(account.get("balance_atomic", 0)))
            exact = Decimal(due) * ratio
            amount = int(exact.to_integral_value(rounding=ROUND_DOWN))
            row = dict(account)
            row["balance_atomic"] = amount
            capped.append(row)
            used += amount
            fractions.append((exact - Decimal(amount), index))

        remainder = available - used
        for _, index in sorted(fractions, reverse=True)[:remainder]:
            capped[index]["balance_atomic"] += 1

        return [a for a in capped if int(a.get("balance_atomic", 0)) > 0]

    async def process_payouts(self):
        accounts = self.db.eligible_payout_accounts(self.minimum_atomic)
        if not accounts:
            logging.info("Scheduled payout check: no eligible miners")
            self._write_status(eligible_miners=0, eligible_atomic=0)
            return "no_eligible_miners"

        eligible_atomic = sum(max(0, int(a.get("balance_atomic", 0))) for a in accounts)
        self._write_status(eligible_miners=len(accounts), eligible_atomic=eligible_atomic)

        try:
            payout_account = await self._resolve_payout_account()
            account_balance = await asyncio.to_thread(
                self.rpc.getaccountbalance,
                payout_account,
                1,
                False,
            )
            wallet_atomic = int(Decimal(str(account_balance or 0)) * COIN)
        except Exception:
            logging.exception("Unable to read payout account balance before payout")
            return "wallet_unavailable"

        accounts = self._cap_accounts_to_wallet(accounts, wallet_atomic)
        if not accounts:
            logging.info(
                "Payout deferred: account=%r balance %.8f YERB does not exceed fee reserve %.8f YERB",
                payout_account,
                wallet_atomic / COIN,
                self.fee_reserve_atomic / COIN,
            )
            return "deferred_fee_reserve"

        # All eligible miners are collected into one payout record and one
        # sendmany RPC transaction for this scheduled two-hour cycle.
        payout_id = self.db.create_payout(accounts)
        items = self.db.payout_items(payout_id)
        if not items:
            return "empty_batch"

        amounts = {
            item["address"]: float(Decimal(item["amount_atomic"]) / Decimal(COIN))
            for item in items
        }
        total_atomic = sum(int(item["amount_atomic"]) for item in items)
        logging.info(
            "Sending combined payout batch id=%s account=%r recipients=%s total=%.8f YERB balance=%.8f reserve=%.8f",
            payout_id,
            payout_account,
            len(items),
            total_atomic / COIN,
            wallet_atomic / COIN,
            self.fee_reserve_atomic / COIN,
        )

        self.db.mark_payout_broadcasting(payout_id)
        try:
            txid = await asyncio.to_thread(
                self.rpc.sendmany,
                amounts,
                f"YERB-Pool payout #{payout_id}",
                payout_account,
            )
        except Exception as exc:
            message = str(exc).lower()
            if "insufficient funds" in message or "invalid amount" in message or "invalid yerbas address" in message:
                self.db.mark_payout_failed(payout_id, exc)
                logging.exception("Payout batch %s failed before broadcast", payout_id)
                return "failed_before_broadcast"
            self.db.mark_payout_uncertain(payout_id, exc)
            logging.exception(
                "Payout batch %s has uncertain broadcast state; manual reconciliation required",
                payout_id,
            )
            return "uncertain"

        self.db.mark_payout_sent(payout_id, str(txid))
        self._write_status(
            eligible_miners=len(items),
            eligible_atomic=total_atomic,
            last_payout_id=payout_id,
            last_payout_txid=str(txid),
            last_payout_recipients=len(items),
            last_payout_atomic=total_atomic,
        )
        logging.warning("PAYOUT SENT id=%s txid=%s recipients=%s", payout_id, txid, len(items))
        return "sent"
