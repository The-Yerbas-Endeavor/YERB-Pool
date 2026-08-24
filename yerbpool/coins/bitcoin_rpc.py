from .base import CoinAdapter

class BitcoinRPCAdapter(CoinAdapter):
    key = "bitcoin-rpc"
    algorithms = ("ghostrider",)

    def validate_daemon(self, rpc):
        chain = rpc.call("getblockchaininfo")
        wallet = rpc.call("getwalletinfo")
        mining = rpc.call("getmininginfo")
        return {"chain": chain.get("chain"), "blocks": chain.get("blocks"),
                "headers": chain.get("headers"), "initial_block_download": chain.get("initialblockdownload"),
                "wallet_balance": wallet.get("balance"), "difficulty": mining.get("difficulty")}
