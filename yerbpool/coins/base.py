from abc import ABC, abstractmethod

class CoinAdapter(ABC):
    key = "base"
    algorithms = ()

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def validate_daemon(self, rpc):
        """Return daemon identity and chain readiness information."""

    def payout_comment(self, purpose="payout"):
        ticker = self.config.get("coin", {}).get("ticker", "COIN")
        return f"{ticker} Pool {purpose}"
