"""polymarket.com taker fills (on-chain). Polygon block time, 1 s resolution, landing ~1-3 s after the
off-chain match. Taker = proxy wallet.

The data API's condition-filtered feed ignores start/end and serves newest first, so fetch() pages back
to the window start. Its cursor does not carry the filter: a cursor-only request silently returns the
global feed, so the filter is resent with every cursor.
"""
from .net import get
from .rows import binary_row

GAMMA = "https://gamma-api.polymarket.com/events"
TRADES = "https://data-api.polymarket.com/v2/trades"


def fetch(event_slug: str, start_ms: int, end_ms: int) -> tuple[dict, list[dict]]:
    """{"markets": event's markets, "trades": unmodified taker records in the window}, and the requests."""
    events = get(GAMMA, {"slug": event_slug})
    if not events:
        raise SystemExit(f"polymarket event {event_slug!r} not found")
    markets = [{"conditionId": m["conditionId"], "slug": m["slug"], "question": m["question"]} for m in events[0]["markets"]]
    ids = [m["conditionId"] for m in markets]
    requests = [{"url": GAMMA, "params": {"slug": event_slug}}]
    trades, seen = [], set()
    for i in range(0, len(ids), 20):
        query = {"condition": ",".join(ids[i:i + 20]), "limit": 1000, "taker_only": "true"}
        requests.append({"url": TRADES, "params": query})
        page = get(TRADES, query)
        while True:
            for t in page["data"]:
                key = (t["transaction_hash"], t["proxy_wallet"], t["token_id"], t["size"], t["price"], t["side"])
                if start_ms <= t["timestamp"] * 1000 < end_ms and key not in seen:
                    seen.add(key)
                    trades.append(t)
            pg = page["pagination"]
            if not page["data"] or page["data"][-1]["timestamp"] * 1000 < start_ms or not pg.get("has_more"):
                break
            page = get(TRADES, {**query, "cursor": pg["next_cursor"]})
    return {"markets": markets, "trades": trades}, requests


def normalize(raw: dict) -> list[dict]:
    slugs = {m["conditionId"]: m["slug"] for m in raw["markets"]}
    rows = []
    for t in raw["trades"]:
        yes = t["outcome_index"] == 0
        side = 1 if yes == (t["side"] == "BUY") else -1
        rows.append(binary_row("polymarket", slugs[t["condition_id"]], t["timestamp"] * 1000, side, float(t["size"]),
                               t["price"] if yes else 1 - t["price"], t["proxy_wallet"]))
    return rows
