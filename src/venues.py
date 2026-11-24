"""Prediction-market taker tapes, normalized to one row per fill, aggressor side only:

  {venue, market, t_ms, side, qty, price, usd, taker}

side +1 = taker bought YES (or sold NO); -1 = taker bought NO. price is the YES price.
usd is the taker's cash at risk: qty*price for +1, qty*(1-price) for -1.

Timestamp quality differs by venue:
  kalshi       matching-engine time, microseconds. Taker identity is not public. Full public history:
               trades older than the archive cutoff move from /markets/trades to /historical/trades.
  polymarket   Polygon block time, 1 s resolution, lands ~1-3 s after the off-chain match. Taker = proxy wallet.
  pmus         no public trade history exists. Only book-derived display prices (price_history),
               roughly one point a minute; trades must be captured live from the markets websocket.
"""
from datetime import datetime

from net import get

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com/events"
PM_TRADES = "https://data-api.polymarket.com/v2/trades"
PMUS_HISTORY = "https://gateway.polymarket.us/v1/price-history"


def _row(venue, market, t_ms, side, qty, price, taker=""):
    return {"venue": venue, "market": market, "t_ms": t_ms, "side": side, "qty": qty, "price": price,
            "usd": qty * (price if side > 0 else 1 - price), "taker": taker}


def _iso_ms(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def kalshi_trades(ticker: str, start_ms: int, end_ms: int) -> list[dict]:
    cutoff = _iso_ms(get(f"{KALSHI}/historical/cutoff")["trades_created_ts"])
    rows = []
    for path, a, b in (("/historical/trades", start_ms, min(end_ms, cutoff)), ("/markets/trades", max(start_ms, cutoff), end_ms)):
        cursor = None
        while a < b:
            page = get(KALSHI + path, {"ticker": ticker, "min_ts": a // 1000, "max_ts": b // 1000 + 1, "limit": 1000, "cursor": cursor})
            for t in page["trades"]:
                ms = _iso_ms(t["created_time"])
                if a <= ms < b:
                    rows.append(_row("kalshi", ticker, ms, 1 if t["taker_side"] == "yes" else -1, float(t["count_fp"]), float(t["yes_price_dollars"])))
            cursor = page.get("cursor")
            if not cursor or not page["trades"]:
                break
    return sorted(rows, key=lambda r: r["t_ms"])


def polymarket_conditions(event_slug: str) -> dict[str, str]:
    """condition id -> market slug for every market in a polymarket.com event."""
    events = get(GAMMA, {"slug": event_slug})
    if not events:
        raise SystemExit(f"polymarket event {event_slug!r} not found")
    return {m["conditionId"]: m["slug"] for m in events[0]["markets"]}


def polymarket_trades(event_slug: str, start_ms: int, end_ms: int) -> list[dict]:
    """The condition-filtered feed ignores start/end and serves newest first, so page back to start_ms.
    The cursor does not carry the filter: a cursor-only request silently returns the global feed."""
    slugs = polymarket_conditions(event_slug)
    ids = list(slugs)
    rows, seen = [], set()
    for i in range(0, len(ids), 20):
        query = {"condition": ",".join(ids[i:i + 20]), "limit": 1000, "taker_only": "true"}
        page = get(PM_TRADES, query)
        while True:
            for t in page["data"]:
                ms = t["timestamp"] * 1000
                key = (t["transaction_hash"], t["proxy_wallet"], t["token_id"], t["size"], t["price"], t["side"])
                if not start_ms <= ms < end_ms or key in seen:
                    continue
                seen.add(key)
                buys_yes = (t["outcome_index"] == 0) == (t["side"] == "BUY")
                yes_px = t["price"] if t["outcome_index"] == 0 else 1 - t["price"]
                rows.append(_row("polymarket", slugs[t["condition_id"]], ms, 1 if buys_yes else -1, float(t["size"]), yes_px, t["proxy_wallet"]))
            pg = page["pagination"]
            if not page["data"] or page["data"][-1]["timestamp"] * 1000 < start_ms or not pg.get("has_more"):
                break
            page = get(PM_TRADES, {**query, "cursor": pg["next_cursor"]})
    return sorted(rows, key=lambda r: r["t_ms"])


def pmus_prices(slug: str, start_ms: int, end_ms: int) -> list[dict]:
    """Polymarket US display prices: yes_ask = best ask, yes_bid = 1 - NO display price. Not trades."""
    page = get(PMUS_HISTORY, {"symbol": slug, "timestamp.startTimestamp": start_ms // 1000, "timestamp.endTimestamp": end_ms // 1000, "fidelity": 1})
    return [{"t_ms": p["timestamp"] * 1000, "yes_ask": p["longPrice"], "yes_bid": round(1 - p["shortPrice"], 4)} for p in page.get("history", [])]
