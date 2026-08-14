import base64
import json
import urllib.error
import urllib.request


class YerbasRPC:
    def __init__(self, cfg):
        self.url = cfg["url"]
        token = f'{cfg["user"]}:{cfg["password"]}'.encode()
        self.auth = "Basic " + base64.b64encode(token).decode()
        self.counter = 0

    def call(self, method, params=None):
        self.counter += 1
        body = json.dumps({
            "jsonrpc": "1.0",
            "id": self.counter,
            "method": method,
            "params": params or [],
        }).encode()
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": self.auth},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                payload = json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            # Yerbas returns JSON-RPC errors with HTTP 500. Preserve the actual
            # daemon error so payout failures are diagnosable instead of being
            # reduced to the generic "HTTP Error 500" message.
            raw = exc.read().decode(errors="replace")
            try:
                payload = json.loads(raw)
            except Exception:
                raise RuntimeError(
                    f"RPC {method} HTTP {exc.code}: {raw or exc.reason}"
                ) from exc
            if payload.get("error"):
                raise RuntimeError(f"RPC {method} failed: {payload['error']}") from exc
            raise RuntimeError(
                f"RPC {method} HTTP {exc.code}: {raw or exc.reason}"
            ) from exc
        if payload.get("error"):
            raise RuntimeError(f"RPC {method} failed: {payload['error']}")
        return payload.get("result")

    def getblocktemplate(self):
        return self.call("getblocktemplate", [{"rules": ["segwit"]}])

    def submitblock(self, block_hex):
        return self.call("submitblock", [block_hex])

    def getblock(self, block_hash):
        return self.call("getblock", [block_hash])

    def getblockcount(self):
        return int(self.call("getblockcount"))

    def getwalletinfo(self):
        return self.call("getwalletinfo")

    def sendmany(self, amounts, comment="YERB-Pool payout"):
        # Yerbas Core expects:
        # sendmany fromaccount {address:amount,...} minconf addlocked comment
        # The previous pool call omitted addlocked and passed the comment in its
        # place, causing a JSON type error before transaction creation.
        return self.call("sendmany", ["", amounts, 1, False, comment])
