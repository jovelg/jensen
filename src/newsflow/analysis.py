"""Burst detection, lead/lag, early-taker edge and the one-clock chart, over a normalized tape."""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def bursts(df: pd.DataFrame, bucket_ms: int, min_usd: float) -> pd.DataFrame:
    """Buckets where YES/long taker buying reached min_usd, in time order, with the biggest taker's share."""
    b = df[df.side > 0].assign(bucket=lambda d: d.t_ms // bucket_ms)
    if b.empty:
        return pd.DataFrame(columns=["clock", "t_ms", "qty", "usd", "px_lo", "px_hi", "top_taker", "top_share"])
    g = b.groupby("bucket").agg(clock=("clock", "first"), t_ms=("t_ms", "first"), qty=("qty", "sum"), usd=("usd", "sum"),
                                px_lo=("price", "min"), px_hi=("price", "max"))
    top = b.groupby(["bucket", "taker"]).usd.sum().reset_index().sort_values("usd").groupby("bucket").last()
    g["top_taker"] = top.taker.str[:10].replace("", "(anonymous)")
    g["top_share"] = top.usd / g.usd
    return g[g.usd >= min_usd].reset_index(drop=True)


def bursts_by_market(tape: pd.DataFrame, rules: dict[str, tuple[int, float]]) -> pd.DataFrame:
    parts = [bursts(df, *rules[venue]).assign(venue=venue, label=label) for (venue, label), df in tape.groupby(["venue", "label"], sort=False)]
    return pd.concat(parts, ignore_index=True)


def first_bursts(b: pd.DataFrame, marks: dict[str, int]) -> pd.DataFrame:
    """Each market's first burst, with lags (s) against the first Hyperliquid burst and every mark."""
    f = b.sort_values("t_ms").groupby("label", sort=False).head(1).reset_index(drop=True)
    hl0 = f[f.venue == "hyperliquid"].t_ms.min()
    if pd.notna(hl0):
        f["vs_first_HL_s"] = (f.t_ms - hl0) / 1000
    for name, t in marks.items():
        f[f"vs_{name}_s"] = (f.t_ms - t) / 1000
    return f


def edge(buys: pd.DataFrame, t0: int, seconds: int) -> pd.Series:
    """YES taker buys in [t0, t0+seconds): cash risked, contracts, VWAP and profit at a $1 settlement."""
    d = buys[buys.t_ms.between(t0, t0 + seconds * 1000 - 1)]
    return pd.Series({"risked_usd": d.usd.sum(), "contracts": d.qty.sum(), "vwap": d.usd.sum() / d.qty.sum() if len(d) else float("nan"),
                      "profit_at_1_usd": (d.qty - d.usd).sum(), "fills": len(d)})


def early_takers(buys: pd.DataFrame, t0: int, seconds: int) -> pd.DataFrame:
    """Per-taker YES buying in [t0, t0+seconds], first fill first, with profit at a $1 settlement."""
    d = buys[buys.t_ms.between(t0, t0 + seconds * 1000)]
    w = d.groupby("taker").agg(first_fill=("clock", "min"), markets=("label", lambda s: ", ".join(sorted(set(s)))),
                               contracts=("qty", "sum"), risked_usd=("usd", "sum"))
    w["avg_px"] = w.risked_usd / w.contracts
    w["profit_at_1_usd"] = w.contracts - w.risked_usd
    return w.sort_values("first_fill")


def chart(tape: pd.DataFrame, pmus: dict[str, pd.DataFrame], ev, t0: int, t1: int, bucket_ms: int = 500):
    def ts(t):
        x = pd.to_datetime(t, unit="ms", utc=True)
        return x.dt.tz_convert(ev.tz) if isinstance(x, pd.Series) else x.tz_convert(ev.tz)

    panels = [(v, title) for v, title in (("hyperliquid", "Hyperliquid perps (long-taker $, price)"),
                                          ("kalshi", "Kalshi (YES-taker $, YES price)"),
                                          ("polymarket", "Polymarket (YES-taker $, YES price; block time)")) if (tape.venue == v).any()]
    fig, axes = plt.subplots(len(panels) + bool(pmus), 1, figsize=(14, 3 * (len(panels) + bool(pmus))), sharex=True, squeeze=False)
    axes = axes[:, 0]
    for ax, (venue, title) in zip(axes, panels):
        d = tape[(tape.venue == venue) & tape.t_ms.between(t0, t1)]
        flow = d[d.side > 0].groupby(d.t_ms // bucket_ms * bucket_ms).usd.sum()
        ax.bar(ts(flow.index), flow.values / 1e3, width=bucket_ms / 86_400_000, align="edge", color="tab:orange", alpha=.8)
        ax.set_ylabel("taker buy $k")
        ax.set_title(title, loc="left", fontsize=10)
        px = ax.twinx()
        for label, g in d.groupby("label"):
            px.step(g.time, g.price, where="post", lw=1, label=label)
        px.legend(fontsize=7, loc="upper left")
    if pmus:
        ax = axes[-1]
        for label, df in pmus.items():
            ax.step(ts(df.t_ms), df.yes_ask, where="post", label=f"{label} ask")
            ax.step(ts(df.t_ms), df.yes_bid, where="post", ls="--", label=f"{label} bid")
        ax.set_title("Polymarket US (display prices, about 1 a minute; no trade tape)", loc="left", fontsize=10)
        ax.legend(fontsize=7, loc="upper left")
    hl0 = tape[(tape.venue == "hyperliquid")]
    first_hl = first_bursts(bursts_by_market(hl0, ev.bursts), {}).t_ms.min() if len(hl0) else None
    for ax in axes:
        for t in ev.marks.values():
            ax.axvline(ts(t), color="k", ls=":", lw=1)
        if first_hl is not None and pd.notna(first_hl):
            ax.axvline(ts(first_hl), color="tab:red", ls="--", lw=1)
        ax.set_xlim(ts(t0), ts(t1))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=ev.tz))
    fig.suptitle(f"{ev.title}. Red dashed: first Hyperliquid burst; dotted: " + ", ".join(ev.marks), fontsize=9)
    fig.tight_layout()
    return fig
