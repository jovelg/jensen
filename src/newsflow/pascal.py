"""Pascal (pascal.trade) public trade tape. Matching-engine timestamps (ms), explicit taker side, and both
wallets (Solana owner keys). No auth for reads.

GET https://data.pascal.trade/api/v1/trades?symbols=... returns newest first; `data.next_cursor` goes back
into `before_cursor` for the next older page. HTTP 503 HISTORY_NOT_READY means the boundary isn't indexed
yet and is retried. A market symbol is one outcome: BID buys it (YES exposure), ASK sells it (NO exposure).
"""
from .net import get
from .rows import binary_row

TRADES = "https://data.pascal.trade/api/v1/trades"


def fetch(symbol: str, start_ms: int, end_ms: int) -> tuple[list[dict], list[dict]]:
    """Unmodified trade records in [start_ms, end_ms), and the request that produced them."""
    params = {"symbols": symbol, "limit": 500}
    records, cursor = [], None
    while True:
        data = get(TRADES, {**params, "before_cursor": cursor})["data"]
        records += [t for t in data["items"] if start_ms <= int(t["trade_ts_ms"]) < end_ms]
        cursor = data.get("next_cursor")
        if not data["items"] or int(data["items"][-1]["trade_ts_ms"]) < start_ms or not cursor:
            break
    return records, [{"url": TRADES, "params": params}]


def normalize(records: list[dict]) -> list[dict]:
    return [binary_row("pascal", t["symbol"], int(t["trade_ts_ms"]), 1 if t["taker_side"] == "BID" else -1,
                       float(t["size"]), float(t["price"]), t["taker"]) for t in records]
