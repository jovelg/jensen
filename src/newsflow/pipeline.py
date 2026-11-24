"""The three reproducible steps for one event: fetch (raw) -> process (tables) -> figures."""
import os
import pathlib

import pandas as pd

from . import analysis, hl, kalshi, pmus, polymarket, rawstore
from .event import Event

ROOT = pathlib.Path(__file__).resolve().parents[2]


def raw_dir(ev: Event) -> pathlib.Path:
    return ROOT / "data" / "raw" / ev.name


def processed_dir(ev: Event) -> pathlib.Path:
    return ROOT / "data" / "processed" / ev.name


def _sources(ev: Event):
    """(raw file name, source description, fetch thunk) for every source in the event."""
    a, b = ev.start_ms, ev.end_ms
    for coin in ev.hl_coins:
        if ev.hl_source == "s3":
            yield f"hl-s3-{coin.replace(':', '_')}", "hyperliquid s3 node_fills_by_block", lambda c=coin: hl.fetch_s3(c, a, b, ROOT / "data" / "hl-s3")
        else:
            yield f"hl-ironflow-{coin.replace(':', '_')}", "ironflow /v1/trades (hyperliquid fills)", lambda c=coin: hl.fetch_ironflow(c, a, b)
    for t in ev.kalshi:
        yield f"kalshi-{t}", "kalshi public trades", lambda t=t: kalshi.fetch(t, a, b)
    for slug in ev.polymarket:
        yield f"polymarket-{slug}", "polymarket gamma event + data-api v2 taker trades", lambda s=slug: polymarket.fetch(s, a, b)
    for slug in ev.pmus:
        yield f"pmus-{slug}", "polymarket us price-history (display prices, not trades)", lambda s=slug: pmus.fetch(s, a, b)


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
        name = f"hl-{ev.hl_source}-{coin.replace(':', '_')}"
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
    df = pd.DataFrame(rows).sort_values("t_ms", kind="stable").reset_index(drop=True)
    df["label"] = df.market.map(labels)
    df["time"] = pd.to_datetime(df.t_ms, unit="ms", utc=True).dt.tz_convert(ev.tz)
    df["clock"] = df.time.dt.strftime("%H:%M:%S.%f").str[:-3]
    return df


def pmus_prices(ev: Event) -> dict[str, pd.DataFrame]:
    out = {}
    for slug, label in ev.pmus.items():
        df = pd.DataFrame(pmus.prices(rawstore.read(raw_dir(ev), f"pmus-{slug}")))
        df["clock"] = pd.to_datetime(df.t_ms, unit="ms", utc=True).dt.tz_convert(ev.tz).dt.strftime("%H:%M:%S")
        out[label] = df
    return out


def process(ev: Event) -> None:
    out = processed_dir(ev)
    out.mkdir(parents=True, exist_ok=True)
    t = tape(ev)
    t.drop(columns="time").to_csv(out / "tape.csv", index=False)
    b = analysis.bursts_by_market(t, ev.bursts)
    b.to_csv(out / "bursts.csv", index=False)
    analysis.first_bursts(b, ev.marks).to_csv(out / "first_bursts.csv", index=False)
    pd.concat(pmus_prices(ev), names=["label"]).reset_index(level=0).to_csv(out / "pmus_prices.csv", index=False)
    print(f"wrote {out}/tape.csv, bursts.csv, first_bursts.csv, pmus_prices.csv")


def figures(ev: Event) -> None:
    out = ROOT / "reports" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    t, prices = tape(ev), pmus_prices(ev)
    hl0 = analysis.first_bursts(analysis.bursts_by_market(t, ev.bursts), ev.marks).query("venue == 'hyperliquid'").t_ms.min()
    zoom0 = int(hl0) - 10_000 if pd.notna(hl0) else ev.start_ms
    for suffix, a, b, bucket in (("zoom", zoom0, zoom0 + 60_000, 500), ("full", ev.start_ms, ev.end_ms, 2000)):
        fig = analysis.chart(t, prices, ev, a, b, bucket)
        fig.savefig(out / f"{ev.name}-{suffix}.png", dpi=130)
        print(f"wrote {out}/{ev.name}-{suffix}.png")
