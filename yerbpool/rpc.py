import base64
import json
import urllib.request

class YerbasRPC:
    def __init__(self, cfg):
        self.url = cfg["url"]
        token = f'{cfg["user"]}:{cfg["password"]}'.encode()
        self.auth = "Basic " + base64.b64encode(token).decode()
        self.counter = 0

    def call(self, method, params=None):
        self.counter += 1
        body = json.dumps({"jsonrpc":"1.0","id":self.counter,"method":method,"params":params or []}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type":"application/json","Authorization":self.auth})
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = json.loads(r.read().decode())
        if payload.get("error"):
            raise RuntimeError(f"RPC {method} failed: {payload['error']}")
        return payload.get("result")

    def getblocktemplate(self):
        return self.call("getblocktemplate", [{"rules":["segwit"]}])

    def submitblock(self, block_hex):
        return self.call("submitblock", [block_hex])
