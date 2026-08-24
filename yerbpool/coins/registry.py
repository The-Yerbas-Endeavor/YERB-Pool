from .bitcoin_rpc import BitcoinRPCAdapter
from .yerbas import YerbasAdapter

ADAPTERS = {item.key: item for item in (BitcoinRPCAdapter, YerbasAdapter)}

def get_adapter(config):
    key = str(config.get("coin", {}).get("adapter", "yerbas")).lower()
    try: adapter = ADAPTERS[key](config)
    except KeyError as exc: raise ValueError(f"unsupported coin adapter: {key}") from exc
    algorithm = str(config.get("coin", {}).get("algorithm", "ghostrider")).lower()
    if algorithm not in adapter.algorithms:
        raise ValueError(f"adapter {key} does not support algorithm {algorithm}")
    return adapter

def supported_algorithms():
    return sorted({algorithm for adapter in ADAPTERS.values() for algorithm in adapter.algorithms})
