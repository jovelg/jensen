"""Normalization and paging rules whose failure would silently corrupt a tape."""
import pytest

from newsflow import hl, kalshi, polymarket


def pm_trade(outcome_index, side, price, size=100.0, ts=1_000):
    return {"outcome_index": outcome_index, "side": side, "price": price, "size": size, "timestamp": ts, "condition_id": "c1",
            "proxy_wallet": "0xw", "transaction_hash": f"0x{outcome_index}{side}{price}{ts}", "token_id": "t"}


@pytest.mark.parametrize(("outcome", "side", "price", "want_side", "want_yes_px", "want_usd"), [
    (0, "BUY", 0.2, 1, 0.2, 20.0),    # buy YES
    (0, "SELL", 0.2, -1, 0.2, 80.0),  # sell YES = NO exposure
    (1, "BUY", 0.3, -1, 0.7, 30.0),   # buy NO at 30c: YES price 70c, risks 30
    (1, "SELL", 0.3, 1, 0.7, 70.0),   # sell NO = YES exposure at 70c
])
def test_polymarket_yes_exposure(outcome, side, price, want_side, want_yes_px, want_usd):
    [row] = polymarket.normalize({"markets": [{"conditionId": "c1", "slug": "m"}], "trades": [pm_trade(outcome, side, price)]})
    assert (row["side"], row["market"], row["t_ms"]) == (want_side, "m", 1_000_000)
    assert row["price"] == pytest.approx(want_yes_px)
    assert row["usd"] == pytest.approx(want_usd)


def test_kalshi_no_taker_risks_complement():
    [row] = kalshi.normalize([{"ticker": "K", "created_time": "2026-11-23T13:55:48.399Z", "taker_side": "no", "count_fp": "10.00", "yes_price_dollars": "0.1700"}])
    assert row["side"] == -1 and row["usd"] == pytest.approx(8.3) and row["t_ms"] == 1795442148399


def test_ironflow_taker_is_newer_order_and_unpaired_dropped():
    legs = [
        {"tid": 1, "oid": 10, "side": "sell", "price": "100", "size": "2", "timestamp": 5, "address": "maker", "market": "xyz:NVDA-PERP"},
        {"tid": 1, "oid": 11, "side": "buy", "price": "100", "size": "2", "timestamp": 5, "address": "taker", "market": "xyz:NVDA-PERP"},
        {"tid": 2, "oid": 12, "side": "buy", "price": "101", "size": "1", "timestamp": 6, "address": "x", "market": "xyz:NVDA-PERP"},
    ]
    [row] = hl.normalize_ironflow(legs)
    assert (row["market"], row["taker"], row["side"], row["usd"]) == ("xyz:NVDA", "taker", 1, 200.0)


def test_s3_taker_is_crossed_leg():
    fill = {"coin": "xyz:NVDA", "time": 5, "px": "100", "sz": "2", "tid": 1}
    [row] = hl.normalize_s3([["maker", {**fill, "side": "B", "crossed": False}], ["taker", {**fill, "side": "A", "crossed": True}]])
    assert (row["taker"], row["side"]) == ("taker", -1)


def test_kalshi_fetch_splits_window_at_archive_cutoff(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None):
        if url.endswith("/historical/cutoff"):
            return {"trades_created_ts": "1970-01-01T00:00:10Z"}
        calls.append((url.removeprefix(kalshi.API), params["min_ts"], params["max_ts"]))
        t = "1970-01-01T00:00:05Z" if "historical" in url else "1970-01-01T00:00:15Z"
        return {"trades": [{"created_time": t}], "cursor": ""}

    monkeypatch.setattr(kalshi, "get", fake_get)
    records, _ = kalshi.fetch("K", 0, 20_000)
    assert calls == [("/historical/trades", 0, 11), ("/markets/trades", 10, 21)]
    assert [r["created_time"] for r in records] == ["1970-01-01T00:00:05Z", "1970-01-01T00:00:15Z"]


def test_polymarket_cursor_requests_keep_condition_filter(monkeypatch):
    seen = []

    def fake_get(url, params=None, headers=None):
        if url == polymarket.GAMMA:
            return [{"markets": [{"conditionId": "c1", "slug": "m", "question": "q"}]}]
        seen.append(params)
        first = "cursor" not in params
        trade = pm_trade(0, "BUY", 0.5, ts=30 if first else 20)
        return {"data": [trade], "pagination": {"has_more": first, "next_cursor": "n"}}

    monkeypatch.setattr(polymarket, "get", fake_get)
    raw, _ = polymarket.fetch("e", 0, 40_000)
    assert len(seen) == 2 and seen[1]["condition"] == "c1" and seen[1]["cursor"] == "n"
    assert len(raw["trades"]) == 2
