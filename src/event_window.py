"""Align taker flow across Hyperliquid, Kalshi, Polymarket and Polymarket US around a news timestamp.

  uv run --with matplotlib news-research/src/event_window.py --name 2026-11-23-jensen \
      --start 2026-11-23T13:55:00Z --end 2026-11-23T13:57:30Z \
      --hl xyz:NVDA --kalshi KXNVDACEO-29JAN-JENS \
      --polymarket jensen-huang-rejoins-nvidia-byptptpt --pmus nphc-nvidiaceo-2028-12-31-jenhua \
      --mark "2026-11-23T13:55:00Z=Press release minute" --mark "2026-11-23T13:55:51.5Z=First X posts"

Writes results/<name>/: trades.csv (normalized taker rows), bursts.txt (first taker bursts per market),
chart.png. Every source pull is cached under data/<name>/ so reruns are offline and keep data whose
upstream window expires (keyless Ironflow reaches only 24 h back). Delete a cache file to refetch.
"""
import argparse
import csv
import json
import pathlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import hl
import venues

ROOT = pathlib.Path(__file__).resolve().parent.parent


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def clock(t_ms: int, tz) -> str:
    return datetime.fromtimestamp(t_ms / 1000, tz).strftime("%H:%M:%S.%f")[:-3]


def cached(path: pathlib.Path, fetch):
    if path.exists():
        return json.loads(path.read_text())
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def bursts(rows: list[dict], bucket_ms: int, min_usd: float, limit: int) -> list[dict]:
    """Buckets where YES/long taker buying reached min_usd, in time order."""
    by = defaultdict(list)
    for r in rows:
        if r["side"] > 0:
            by[r["t_ms"] // bucket_ms].append(r)
    out = []
    for b in sorted(by):
        rs = by[b]
        usd = sum(r["usd"] for r in rs)
        if usd < min_usd:
            continue
        who = defaultdict(float)
        for r in rs:
            who[r["taker"]] += r["usd"]
        top, top_usd = max(who.items(), key=lambda kv: kv[1])
        out.append({"t_ms": rs[0]["t_ms"], "qty": sum(r["qty"] for r in rs), "usd": usd, "lo": min(r["price"] for r in rs),
                    "hi": max(r["price"] for r in rs), "top": top, "top_share": top_usd / usd})
        if len(out) == limit:
            break
    return out


def chart(path, panels, pmus, marks, start, end, bucket_ms, tz):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    def dt(t):
        return datetime.fromtimestamp(t / 1000, tz)

    n = len(panels) + (1 if pmus else 0)
    fig, axes = plt.subplots(n, 1, figsize=(13, 2.6 * n), sharex=True, squeeze=False)
    axes = axes[:, 0]
    for ax, (title, rows) in zip(axes, panels):
        flow = defaultdict(float)
        for r in rows:
            if r["side"] > 0:
                flow[r["t_ms"] // bucket_ms * bucket_ms] += r["usd"]
        ax.bar([dt(t) for t in flow], [v / 1e3 for v in flow.values()], width=bucket_ms / 86_400_000, color="tab:orange", align="edge")
        ax.set_ylabel("taker buy $k")
        px = ax.twinx()
        for market in sorted({r["market"] for r in rows}):
            rs = [r for r in rows if r["market"] == market]
            px.step([dt(r["t_ms"]) for r in rs], [r["price"] for r in rs], where="post", lw=1, label=market)
        px.set_ylabel("price")
        if len({r["market"] for r in rows}) > 1:
            px.legend(fontsize=7, loc="upper left")
        ax.set_title(title, fontsize=10, loc="left")
    if pmus:
        ax = axes[-1]
        for slug, pts in pmus.items():
            ax.step([dt(p["t_ms"]) for p in pts], [p["yes_ask"] for p in pts], where="post", label=f"{slug} yes ask")
            ax.step([dt(p["t_ms"]) for p in pts], [p["yes_bid"] for p in pts], where="post", ls="--", label=f"{slug} yes bid")
        ax.set_title("Polymarket US (book-derived display prices; no public trade tape)", fontsize=10, loc="left")
        ax.legend(fontsize=7, loc="upper left")
    for ax in axes:
        for t, label in marks:
            ax.axvline(dt(t), color="k", ls=":", lw=1)
        ax.set_xlim(dt(start), dt(end))
    for t, label in marks:
        axes[0].annotate(label, (dt(t), 1.0), xycoords=("data", "axes fraction"), rotation=90, fontsize=7, va="top", ha="right")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=tz))
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--start", required=True, help="ISO UTC, e.g. 2026-11-23T13:55:00Z")
    p.add_argument("--end", required=True)
    p.add_argument("--hl", action="append", default=[], help="Hyperliquid coin, e.g. xyz:NVDA (hl.find to discover)")
    p.add_argument("--hl-source", choices=["ironflow", "s3"], default="ironflow")
    p.add_argument("--kalshi", action="append", default=[], help="Kalshi market ticker")
    p.add_argument("--polymarket", action="append", default=[], help="polymarket.com event slug")
    p.add_argument("--pmus", action="append", default=[], help="Polymarket US market slug")
    p.add_argument("--mark", action="append", default=[], help="ISO_UTC=label vertical marker")
    p.add_argument("--bucket", type=float, default=0.5, help="seconds per bar/burst bucket")
    p.add_argument("--min-usd", type=float, default=5000, help="taker buy $ per bucket that counts as a burst")
    p.add_argument("--bursts", type=int, default=8)
    p.add_argument("--utc-offset", type=float, default=-5, help="display offset in hours (ET: -5 EST, -4 EDT)")
    a = p.parse_args()

    start, end, bucket_ms = ms(a.start), ms(a.end), int(a.bucket * 1000)
    tz = timezone(timedelta(hours=a.utc_offset))
    cache, out = ROOT / "data" / a.name, ROOT / "results" / a.name
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{start}-{end}"

    panels = []
    for coin in a.hl:
        fetch = (lambda c=coin: hl.s3_fills(c, start, end, ROOT / "data" / "hl-s3")) if a.hl_source == "s3" else (lambda c=coin: hl.fills(c, start, end))
        panels.append((f"Hyperliquid {coin} perp (taker buys, notional)", cached(cache / f"hl-{a.hl_source}-{coin.replace(':', '_')}-{tag}.json", fetch)))
    for t in a.kalshi:
        panels.append((f"Kalshi {t} (YES taker buys)", cached(cache / f"kalshi-{t}-{tag}.json", lambda t=t: venues.kalshi_trades(t, start, end))))
    for e in a.polymarket:
        panels.append((f"Polymarket {e} (YES taker buys, block time)", cached(cache / f"polymarket-{e}-{tag}.json", lambda e=e: venues.polymarket_trades(e, start, end))))
    pmus = {s: cached(cache / f"pmus-{s}-{tag}.json", lambda s=s: venues.pmus_prices(s, start, end)) for s in a.pmus}
    marks = [(ms(m.split("=", 1)[0]), m.split("=", 1)[1]) for m in a.mark]

    rows = sorted((r for _, rs in panels for r in rs), key=lambda r: r["t_ms"])
    with open(out / "trades.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["clock", "venue", "market", "t_ms", "side", "qty", "price", "usd", "taker"])
        w.writeheader()
        for r in rows:
            w.writerow({"clock": clock(r["t_ms"], tz), **r})

    lines = [f"window {clock(start, tz)}-{clock(end, tz)} (UTC{a.utc_offset:+g}); burst = >= ${a.min_usd:,.0f} YES/long taker buying in {a.bucket:g}s"]
    lines += [f"  mark {clock(t, tz)}  {label}" for t, label in marks]
    for title, rs in panels:
        lines.append(f"\n{title}: {len(rs)} taker fills")
        for b in bursts(rs, bucket_ms, a.min_usd, a.bursts):
            lines.append(f"  {clock(b['t_ms'], tz)}  ${b['usd']:>11,.0f}  qty {b['qty']:>12,.1f}  px {b['lo']:.4g}-{b['hi']:.4g}  top {b['top'][:10] or '-'} {b['top_share']:.0%}")
    for slug, pts in pmus.items():
        lines.append(f"\nPolymarket US {slug} display prices")
        lines += [f"  {clock(p['t_ms'], tz)}  yes bid {p['yes_bid']:.2f} / ask {p['yes_ask']:.2f}" for p in pts]
    (out / "bursts.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    chart(out / "chart.png", panels, pmus, marks, start, end, bucket_ms, tz)
    print(f"\nwrote {out}/trades.csv, bursts.txt, chart.png")


if __name__ == "__main__":
    main()
