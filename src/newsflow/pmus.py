"""Polymarket US. No public trade history exists: the trade search API returns only the caller's own
trades, so trades must be captured live from the markets websocket. What can be fetched afterwards is
the book-derived display price history, roughly one point a minute; the same timestamp can come back
with different values on different queries.
"""
from .net import get

HISTORY = "https://gateway.polymarket.us/v1/price-history"


def fetch(slug: str, start_ms: int, end_ms: int) -> tuple[list[dict], list[dict]]:
    params = {"symbol": slug, "timestamp.startTimestamp": start_ms // 1000, "timestamp.endTimestamp": end_ms // 1000, "fidelity": 1}
    return get(HISTORY, params).get("history", []), [{"url": HISTORY, "params": params}]


def prices(records: list[dict]) -> list[dict]:
    """yes_ask = longPrice (best ask); yes_bid = 1 - shortPrice (NO display price). Not trades."""
    return [{"t_ms": p["timestamp"] * 1000, "yes_ask": p["longPrice"], "yes_bid": round(1 - p["shortPrice"], 4)} for p in records]
