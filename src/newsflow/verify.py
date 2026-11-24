"""Check Ironflow's Hyperliquid fills against Hyperliquid's own API.

candles():     per-minute trade count, base volume and OHLC rebuilt from Ironflow vs HL's 1m candles.
user_fills():  for wallets HL still serves, every HL fill must exist in Ironflow with the same price,
               size, time, order id and side; and our taker inference (newer order id) is scored
               against HL's `crossed` flag.
"""
import pandas as pd


def _trades(records: list[dict]) -> pd.DataFrame:
    """One row per trade (tid), from Ironflow's two-legged records."""
    d = pd.DataFrame(records)
    d["px"], d["sz"] = d.price.astype(float), d["size"].astype(float)
    return d.sort_values(["timestamp", "sequence"]).drop_duplicates("tid")


def candles(records: list[dict], hl_candles: list[dict], tz) -> pd.DataFrame:
    t = _trades(records)
    rows = []
    for c in hl_candles:
        m = t[t.timestamp.between(c["t"], c["T"])]
        rows.append({"minute": pd.Timestamp(c["t"], unit="ms", tz="UTC").tz_convert(tz).strftime("%H:%M"),
                     "hl_trades": c["n"], "ironflow_trades": len(m),
                     "hl_volume": float(c["v"]), "ironflow_volume": round(m.sz.sum(), 6),
                     "hl_ohlc": "/".join(c[k] for k in "ohlc"),
                     "ironflow_ohlc": "/".join(f"{x:g}" for x in (m.px.iloc[0], m.px.max(), m.px.min(), m.px.iloc[-1])) if len(m) else ""})
    out = pd.DataFrame(rows)
    out["match"] = ((out.hl_trades == out.ironflow_trades) & ((out.hl_volume - out.ironflow_volume).abs() < 1e-6)
                    & (out.hl_ohlc.str.split("/").apply(lambda v: [float(x) for x in v]) == out.ironflow_ohlc.str.split("/").apply(lambda v: [float(x) for x in v] if v != [""] else [])))
    return out


def user_fills(records: list[dict], hl_fills: dict[str, list[dict]]) -> dict:
    """Summary counts plus one row per HL fill: found in Ironflow, fields identical, inferred taker vs crossed."""
    by_key = {(f["tid"], f["address"]): f for f in records}
    legs: dict[int, list[dict]] = {}
    for f in records:
        legs.setdefault(f["tid"], []).append(f)
    rows = []
    for addr, fills in hl_fills.items():
        for h in fills:
            m = by_key.get((h["tid"], addr))
            pair = legs.get(h["tid"], [])
            inferred = len(pair) == 2 and max(pair, key=lambda f: f["oid"])["address"] == addr
            rows.append({
                "address": addr, "tid": h["tid"], "time_ms": h["time"], "px": h["px"], "sz": h["sz"], "crossed": h["crossed"], "dir": h["dir"],
                "in_ironflow": m is not None,
                "identical": m is not None and float(m["price"]) == float(h["px"]) and float(m["size"]) == float(h["sz"])
                and m["timestamp"] == h["time"] and m["oid"] == h["oid"] and (m["side"] == "buy") == (h["side"] == "B"),
                "inferred_taker": inferred, "taker_ok": inferred == h["crossed"],
            })
    df = pd.DataFrame(rows)
    return {"wallets": len(hl_fills), "fills": len(df), "in_ironflow": int(df.in_ironflow.sum()), "identical": int(df.identical.sum()),
            "taker_ok": int(df.taker_ok.sum()), "rows": df}
