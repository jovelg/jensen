"""The three reproducible steps for one event: fetch (raw) -> process (tables) -> figures."""
import os
import pathlib

import pandas as pd

from . import analysis, hl, kalshi, pascal, polymarket, rawstore, timing, verify
from .event import Event

ROOT = pathlib.Path(__file__).resolve().parents[2]


def raw_dir(ev: Event) -> pathlib.Path:
    return ROOT / "data" / "raw" / ev.name


def processed_dir(ev: Event) -> pathlib.Path:
    return ROOT / "data" / "processed" / ev.name


def _coin(coin: str) -> str:
    return coin.replace(":", "_")


def _sources(ev: Event):
    """(raw file name, source description, fetch thunk) in dependency order."""
    a, b = ev.start_ms, ev.end_ms
    for coin in ev.hl_coins:
        if ev.hl_source == "s3":
            yield f"hl-s3-{_coin(coin)}", "hyperliquid s3 node_fills_by_block", lambda c=coin: hl.fetch_s3(c, a, b, ROOT / "data" / "hl-s3")
        else:
            fills = f"hl-ironflow-{_coin(coin)}"
            yield fills, "ironflow /v1/trades (hyperliquid fills)", lambda c=coin: hl.fetch_ironflow(c, a, b)
            # First-party Hyperliquid evidence used to verify the Ironflow fills (verify.py).
            yield f"hl-candles-{_coin(coin)}", "hyperliquid info candleSnapshot 1m", lambda c=coin: hl.fetch_candles(c, a, b)
            yield (f"hl-userfills-{_coin(coin)}", "hyperliquid info userFillsByTime (wallets active in the window)",
                   lambda c=coin, f=fills: hl.fetch_user_fills(c, a, b, hl.active_wallets(rawstore.read(raw_dir(ev), f))))
    for t in ev.kalshi:
        yield f"kalshi-{t}", "kalshi public trades", lambda t=t: kalshi.fetch(t, a, b)
    for slug in ev.polymarket:
        yield f"polymarket-{slug}", "polymarket gamma event + data-api v2 taker trades", lambda s=slug: polymarket.fetch(s, a, b)
    for sym in ev.pascal:
        yield f"pascal-{sym}", "pascal public trades", lambda s=sym: pascal.fetch(s, a, b)


def fetch(ev: Event) -> None:
    """Pull every missing raw file. Existing raw files are never refetched; delete one to force it."""
    for name, source, pull in _sources(ev):
        if rawstore.path(raw_dir(ev), name).exists():
            print(f"have  {name}")
            continue
        data, requests = pull()
        rawstore.write(raw_dir(ev), name, data, source, requests)
        print(f"wrote {name}")


def tape(ev: Event) -> pd.DataFrame:
    """Normalized taker rows for every trade source, labelled and stamped in the event's timezone."""
    rows, labels = [], {}
    raw = raw_dir(ev)
    for coin in ev.hl_coins:
        name = f"hl-{ev.hl_source}-{_coin(coin)}"
        norm = hl.normalize_s3 if ev.hl_source == "s3" else hl.normalize_ironflow
        rows += norm(rawstore.read(raw, name))
        labels[coin] = f"HL {coin}"
    for t, label in ev.kalshi.items():
        rows += kalshi.normalize(rawstore.read(raw, f"kalshi-{t}"))
        labels[t] = label
    for slug, prefix in ev.polymarket.items():
        data = rawstore.read(raw, f"polymarket-{slug}")
        rows += polymarket.normalize(data)
        slugs = [m["slug"] for m in data["markets"]]
        common = os.path.commonprefix(slugs) if len(slugs) > 1 else ""
        labels |= {s: f"{prefix} {s[len(common):]}".strip() for s in slugs}
    for sym, label in ev.pascal.items():
        rows += pascal.normalize(rawstore.read(raw, f"pascal-{sym}"))
        labels[sym] = label
    df = pd.DataFrame(rows).sort_values("t_ms", kind="stable").reset_index(drop=True)
    df["label"] = df.market.map(labels)
    df["time"] = pd.to_datetime(df.t_ms, unit="ms", utc=True).dt.tz_convert(ev.tz)
    df["clock"] = df.time.dt.strftime("%H:%M:%S.%f").str[:-3]
    return df


def hl_checks(ev: Event) -> dict[str, dict]:
    """Per Ironflow coin: candle and per-wallet fill comparisons against Hyperliquid's own API."""
    if ev.hl_source != "ironflow":
        return {}
    raw = raw_dir(ev)
    out = {}
    for coin in ev.hl_coins:
        records = rawstore.read(raw, f"hl-ironflow-{_coin(coin)}")
        out[coin] = {"candles": verify.candles(records, rawstore.read(raw, f"hl-candles-{_coin(coin)}"), ev.tz),
                     "fills": verify.user_fills(records, rawstore.read(raw, f"hl-userfills-{_coin(coin)}"))}
    return out


def process(ev: Event) -> None:
    out = processed_dir(ev)
    out.mkdir(parents=True, exist_ok=True)
    t = tape(ev)
    t.drop(columns="time").to_csv(out / "tape.csv", index=False)
    b = analysis.bursts_by_market(t, ev.bursts)
    b.to_csv(out / "bursts.csv", index=False)
    analysis.first_bursts(b, ev.marks).to_csv(out / "first_bursts.csv", index=False)
    for coin, c in hl_checks(ev).items():
        c["candles"].to_csv(out / f"hl-check-candles-{_coin(coin)}.csv", index=False)
        c["fills"]["rows"].to_csv(out / f"hl-check-fills-{_coin(coin)}.csv", index=False)
    print(f"wrote {out}")


def figures(ev: Event) -> None:
    out = ROOT / "reports" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    t = tape(ev)
    hl0 = analysis.first_bursts(analysis.bursts_by_market(t, ev.bursts), ev.marks).query("venue == 'hyperliquid'").t_ms.min()
    zoom0 = int(hl0) - 10_000 if pd.notna(hl0) else ev.start_ms
    for suffix, a, b, bucket, notes in (("zoom", zoom0, zoom0 + 60_000, 500, 4), ("full", ev.start_ms, ev.end_ms, 2000, 0)):
        fig = analysis.chart(t, ev, a, b, bucket, annotate=notes)
        fig.savefig(out / f"{ev.name}-{suffix}.png", dpi=130)
        print(f"wrote {out}/{ev.name}-{suffix}.png")
    for suffix, a, b in (("overlay-zoom", zoom0, zoom0 + 60_000), ("overlay-full", ev.start_ms, ev.end_ms)):
        analysis.overlay(t, ev, a, b).savefig(out / f"{ev.name}-{suffix}.png", dpi=130)
        print(f"wrote {out}/{ev.name}-{suffix}.png")
    if ev.share and ev.release:
        fig = analysis.share(t, ev, x_posts(ev), ev.share["title"], ev.share["subtitle"], ev.share["footer"], ev.share.get("official_x"))
        fig.savefig(out / f"{ev.name}-share.png", dpi=200)
        print(f"wrote {out}/{ev.name}-share.png")


def x_posts(ev: Event) -> list[tuple[str, int]]:
    """(who, t_ms) for the event's X posts: the 'First X posts' mark plus every post id in release-timing."""
    posts = [("first posts", ev.marks["First X posts"])] if "First X posts" in ev.marks else []
    if rawstore.path(raw_dir(ev), "release-timing").exists():
        posts += [(f"@{x['account']}", timing.snowflake_ms(x["id"])) for x in rawstore.read(raw_dir(ev), "release-timing")["x_posts"]]
    return sorted(posts, key=lambda p: p[1])
