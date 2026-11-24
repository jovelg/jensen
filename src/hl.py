"""Hyperliquid market data for event studies. No Hyperliquid key is needed for anything here.

Sources, coarse to fine:
  candles()   Info API candleSnapshot. 1m minimum; only the newest 5000 candles per interval.
  fills()     Ironflow /v1/trades tick fills (HL itself serves no market-wide history).
              Keyless: 24 h back, 1 h per request, 30 req/min. IRONFLOW_API_KEY: 14 days, 6 h, 60/min.
  s3_fills()  s3://hl-mainnet-node-data/node_fills_by_block (requester-pays, ap-northeast-1).
              Every fill since late Jul 2025 incl. HIP-3 dexes; needs working AWS credentials,
              the `aws` CLI and `lz4`. Each hour file holds all of Hyperliquid, so it is cached.

Taker rows use the normalized trade shape from venues.py: one row per trade, aggressor side only.
"""
import json
import os
import pathlib
import subprocess
import time

from net import get, post

INFO = "https://api.hyperliquid.xyz/info"
IRONFLOW = "https://api.ironflow.sh/v1/trades"
S3_BUCKET = "s3://hl-mainnet-node-data/node_fills_by_block/hourly"


def dexes() -> list[str]:
    """"" is the native dex; the rest are HIP-3 builder dexes (xyz, flx, km, cash, ...)."""
    return [""] + [d["name"] for d in post(INFO, {"type": "perpDexs"}) if d]


def find(pattern: str) -> list[str]:
    """Perp coins whose name contains `pattern` across every dex, e.g. find("NVDA") -> ["xyz:NVDA", ...]."""
    pattern = pattern.upper()
    out = []
    for dex in dexes():
        meta = post(INFO, {"type": "meta", "dex": dex} if dex else {"type": "meta"})
        out += [u["name"] for u in meta.get("universe", []) if pattern in u["name"].upper() and not u.get("isDelisted")]
    return out


def candles(coin: str, start_ms: int, end_ms: int, interval: str = "1m") -> list[dict]:
    out, t = [], start_ms
    while t < end_ms:
        page = post(INFO, {"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": t, "endTime": end_ms}})
        if not page:
            break
        out += page
        t = page[-1]["T"] + 1
    return [{"t_ms": c["t"], "o": float(c["o"]), "h": float(c["h"]), "l": float(c["l"]), "c": float(c["c"]), "v": float(c["v"]), "n": c["n"]} for c in out]


def _taker_rows(coin: str, takers) -> list[dict]:
    rows = [{"venue": "hyperliquid", "market": coin, "t_ms": int(t["time"]), "side": 1 if t["side"] in ("B", "buy") else -1,
             "qty": float(t["sz"]), "price": float(t["px"]), "usd": float(t["px"]) * float(t["sz"]), "taker": t["user"]} for t in takers]
    rows.sort(key=lambda r: r["t_ms"])
    return rows


def fills(coin: str, start_ms: int, end_ms: int) -> list[dict]:
    """Ironflow tick fills -> taker rows. Ironflow returns both legs without `crossed`; the leg whose
    order id is newer is the one that crossed the resting book."""
    key = os.environ.get("IRONFLOW_API_KEY")
    window = (6 if key else 1) * 3600_000
    headers = {"Authorization": f"Bearer {key}"} if key else None
    trades: dict[int, list[dict]] = {}
    for a in range(start_ms, end_ms, window):
        cursor = None
        while True:
            page = get(IRONFLOW, {"market": f"{coin}-PERP", "from": a, "to": min(a + window, end_ms), "limit": 1000, "order": "asc", "cursor": cursor}, headers)
            for f in page.get("data", []):
                trades.setdefault(f["tid"], []).append({"px": f["price"], "sz": f["size"], "side": f["side"], "time": f["timestamp"], "user": f["address"], "oid": f["oid"]})
            pg = page.get("pagination", {})
            if not pg.get("has_more"):
                break
            cursor = pg["next_cursor"]
            if not key:
                time.sleep(2.1)
    return _taker_rows(coin, (max(legs, key=lambda f: f["oid"]) for legs in trades.values() if len(legs) == 2))


def s3_fills(coin: str, start_ms: int, end_ms: int, cache: pathlib.Path) -> list[dict]:
    """Archive fills -> taker rows (`crossed` marks the aggressor). Downloads whole UTC hours."""
    cache.mkdir(parents=True, exist_ok=True)
    takers: dict[int, dict] = {}
    for hour in range(start_ms // 3600_000, (end_ms - 1) // 3600_000 + 1):
        t = time.gmtime(hour * 3600)
        rel = f"{time.strftime('%Y%m%d', t)}/{t.tm_hour}.lz4"
        path = cache / rel.replace("/", "-")
        if not path.exists():
            tmp = path.with_suffix(".part")
            subprocess.run(["aws", "s3", "cp", f"{S3_BUCKET}/{rel}", str(tmp), "--request-payer", "requester", "--region", "ap-northeast-1", "--only-show-errors"], check=True)
            tmp.rename(path)
        with subprocess.Popen(["lz4", "-dc", str(path)], stdout=subprocess.PIPE, text=True) as p:
            for line in p.stdout:
                if f'"{coin}"' not in line:
                    continue
                for user, f in json.loads(line)["events"]:
                    if f["coin"] == coin and f["crossed"] and start_ms <= f["time"] < end_ms:
                        takers[f["tid"]] = {**f, "user": user}
    return _taker_rows(coin, takers.values())
