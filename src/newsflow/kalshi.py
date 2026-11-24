"""Kalshi public trade tape. Matching-engine timestamps (microseconds); takers are anonymous.

Trades older than the archive cutoff (GET /historical/cutoff, `trades_created_ts`) move from
/markets/trades to /historical/trades; fetch() reads whichever side of the cutoff the window covers.
"""
from datetime import datetime

from .net import get
from .rows import binary_row

API = "https://api.elections.kalshi.com/trade-api/v2"


def iso_ms(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def fetch(ticker: str, start_ms: int, end_ms: int) -> tuple[list[dict], list[dict]]:
    """Unmodified trade records in [start_ms, end_ms), and the requests that produced them."""
    cutoff = iso_ms(get(f"{API}/historical/cutoff")["trades_created_ts"])
    records, requests = [], []
    for path, a, b in (("/historical/trades", start_ms, min(end_ms, cutoff)), ("/markets/trades", max(start_ms, cutoff), end_ms)):
        if a >= b:
            continue
        params = {"ticker": ticker, "min_ts": a // 1000, "max_ts": b // 1000 + 1, "limit": 1000}
        requests.append({"url": API + path, "params": params})
        cursor = None
        while True:
            page = get(API + path, {**params, "cursor": cursor})
            records += [t for t in page["trades"] if a <= iso_ms(t["created_time"]) < b]
            cursor = page.get("cursor")
            if not cursor or not page["trades"]:
                break
    return records, requests


def normalize(records: list[dict]) -> list[dict]:
    return [binary_row("kalshi", t["ticker"], iso_ms(t["created_time"]), 1 if t["taker_side"] == "yes" else -1,
                       float(t["count_fp"]), float(t["yes_price_dollars"])) for t in records]
