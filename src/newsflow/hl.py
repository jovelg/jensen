"""Hyperliquid market data. No Hyperliquid key is needed for anything here.

Sources, coarse to fine:
  candles()        Info API candleSnapshot. 1m minimum; only the newest 5000 candles per interval.
  fetch_ironflow() Ironflow /v1/trades tick fills (Hyperliquid itself serves no market-wide history).
                   Keyless: 24 h back, 1 h per request, 30 req/min. IRONFLOW_API_KEY: 14 days, 6 h, 60/min.
  fetch_s3()       s3://hl-mainnet-node-data/node_fills_by_block (requester-pays, ap-northeast-1).
                   Every fill since late Jul 2025 incl. HIP-3 dexes; needs working AWS credentials,
                   the `aws` CLI and `lz4`. Each hour file holds all of Hyperliquid, so it is cached.
"""
import json
import os
import pathlib
import subprocess
import time

from .net import get, post
from .rows import perp_row

INFO = "https://api.hyperliquid.xyz/info"
IRONFLOW = "https://api.ironflow.sh/v1/trades"
S3_BUCKET = "s3://hl-mainnet-node-data/node_fills_by_block/hourly"


def dexes() -> list[str]:
    """"" is the native dex; the rest are HIP-3 builder dexes (xyz, io, ...)."""
    return [""] + [d["name"] for d in post(INFO, {"type": "perpDexs"}) if d]


def find(pattern: str) -> list[str]:
    """Listed perp coins whose name contains `pattern` across every dex, e.g. find("NVDA") -> ["xyz:NVDA", ...]."""
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


def fetch_ironflow(coin: str, start_ms: int, end_ms: int) -> tuple[list[dict], list[dict]]:
    """Unmodified Ironflow fill records (both legs of every trade) in the window, and the requests."""
    key = os.environ.get("IRONFLOW_API_KEY")
    window = (6 if key else 1) * 3600_000
    headers = {"Authorization": f"Bearer {key}"} if key else None
    records, requests = [], []
    for a in range(start_ms, end_ms, window):
        params = {"market": f"{coin}-PERP", "from": a, "to": min(a + window, end_ms), "limit": 1000, "order": "asc"}
        requests.append({"url": IRONFLOW, "params": params, "api_key": bool(key)})
        cursor = None
        while True:
            page = get(IRONFLOW, {**params, "cursor": cursor}, headers)
            records += page.get("data", [])
            pg = page.get("pagination", {})
            if not pg.get("has_more"):
                break
            cursor = pg["next_cursor"]
            if not key:
                time.sleep(2.1)
    return records, requests


def normalize_ironflow(records: list[dict]) -> list[dict]:
    """Ironflow omits `crossed`. Of a trade's two legs, the one with the newer order id crossed the
    resting book, so it is the taker. Trades missing a leg are dropped."""
    legs: dict[int, list[dict]] = {}
    for f in records:
        legs.setdefault(f["tid"], []).append(f)
    rows = []
    for pair in legs.values():
        if len(pair) != 2:
            continue
        t = max(pair, key=lambda f: f["oid"])
        rows.append(perp_row("hyperliquid", t["market"].removesuffix("-PERP"), t["timestamp"], 1 if t["side"] == "buy" else -1,
                             float(t["size"]), float(t["price"]), t["address"]))
    return rows


def fetch_s3(coin: str, start_ms: int, end_ms: int, cache: pathlib.Path) -> tuple[list[list], list[dict]]:
    """Unmodified [address, fill] events for `coin` in the window, from whole cached UTC hour files."""
    cache.mkdir(parents=True, exist_ok=True)
    events, requests = [], []
    for hour in range(start_ms // 3600_000, (end_ms - 1) // 3600_000 + 1):
        t = time.gmtime(hour * 3600)
        url = f"{S3_BUCKET}/{time.strftime('%Y%m%d', t)}/{t.tm_hour}.lz4"
        requests.append({"url": url, "params": {"request_payer": "requester", "region": "ap-northeast-1"}})
        path = cache / url.removeprefix(S3_BUCKET + "/").replace("/", "-")
        if not path.exists():
            tmp = path.with_suffix(".part")
            subprocess.run(["aws", "s3", "cp", url, str(tmp), "--request-payer", "requester", "--region", "ap-northeast-1", "--only-show-errors"], check=True)
            tmp.rename(path)
        with subprocess.Popen(["lz4", "-dc", str(path)], stdout=subprocess.PIPE, text=True) as p:
            for line in p.stdout:
                if f'"{coin}"' in line:
                    events += [[user, f] for user, f in json.loads(line)["events"] if f["coin"] == coin and start_ms <= f["time"] < end_ms]
    return events, requests


def normalize_s3(events: list[list]) -> list[dict]:
    """`crossed` marks the taker leg."""
    return [perp_row("hyperliquid", f["coin"], f["time"], 1 if f["side"] == "B" else -1, float(f["sz"]), float(f["px"]), user)
            for user, f in events if f["crossed"]]
