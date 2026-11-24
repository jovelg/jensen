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


def _k(x: float) -> str:
    for div, unit in ((1e6, "M"), (1e3, "K")):
        if abs(x) >= div:
            v = x / div
            return f"{v:.2f}{unit}" if v < 10 else f"{v:.1f}{unit}" if v < 100 else f"{v:.0f}{unit}"
    return f"{x:.0f}"


def _cents(lo: float, hi: float) -> str:
    a, b = round(lo * 100), round(hi * 100)
    return f"{a}¢" if a == b else f"{a}–{b}¢"


def callout(burst: pd.Series, venue: str, market: str | None) -> str:
    """Burst label in the PM Pulse style; binaries add cash risked and the payout at $1.
    Dollar signs are escaped so matplotlib doesn't read them as math."""
    clock = burst.clock[:10]
    if venue == "hyperliquid":
        px = f"{burst.px_lo:.2f}" if burst.px_lo == burst.px_hi else f"{burst.px_lo:.2f}–{burst.px_hi:.2f}"
        return f"\\${_k(burst.usd)} long\n{px}\n{burst.top_taker}… {burst.top_share:.0%}\n{clock}"
    head = f"{market}\n" if market else ""
    return f"{head}{_k(burst.qty)} contracts\n{_cents(burst.px_lo, burst.px_hi)}\n\\${_k(burst.usd)} → win \\${_k(burst.qty - burst.usd)}\n{clock}"


def window_totals(d: pd.DataFrame, venue: str) -> str:
    b = d[d.side > 0]
    if venue == "hyperliquid":
        return f"long takers \\${_k(b.usd.sum())}, short takers \\${_k(d[d.side < 0].usd.sum())}"
    return f"YES takers: {_k(b.qty.sum())} contracts, \\${_k(b.usd.sum())} risked to win \\${_k((b.qty - b.usd).sum())}"


def chart(tape: pd.DataFrame, ev, t0: int, t1: int, bucket_ms: int = 500, annotate: int = 0):
    """One panel per venue: taker-buy $ bars per bucket and price steps. `annotate` labels each panel's
    first burst plus its largest ones (event burst rules, `annotate` in total) with size, price range,
    $ risked and payout."""
    def ts(t):
        x = pd.to_datetime(t, unit="ms", utc=True)
        return x.dt.tz_convert(ev.tz) if isinstance(x, pd.Series) else x.tz_convert(ev.tz)

    panels = [(v, title) for v, title in (("hyperliquid", "Hyperliquid perps: long-taker $ per bar, price"),
                                          ("kalshi", "Kalshi: YES-taker $ per bar, YES price"),
                                          ("polymarket", "Polymarket: YES-taker $ per bar, YES price (block time)"),
                                          ("pascal", "Pascal: YES-taker $ per bar, YES price")) if (tape.venue == v).any()]
    fig, axes = plt.subplots(len(panels), 1, figsize=(15, 4.2 * len(panels)), sharex=True, squeeze=False)
    axes = axes[:, 0]
    first_hl = first_bursts(bursts_by_market(tape[tape.venue == "hyperliquid"], ev.bursts), {}).t_ms.min() if (tape.venue == "hyperliquid").any() else None
    for ax, (venue, title) in zip(axes, panels):
        d = tape[(tape.venue == venue) & tape.t_ms.between(t0, t1)]
        flow = d[d.side > 0].groupby(d.t_ms // bucket_ms * bucket_ms).usd.sum()
        ax.bar(ts(flow.index), flow.values / 1e3, width=bucket_ms / 86_400_000, align="edge", color="tab:orange", alpha=.85)
        ax.set_ylabel(f"taker buy $k / {bucket_ms / 1000:g} s")
        ax.set_title(f"{title}   [{window_totals(d, venue)}]", loc="left", fontsize=10)
        px = ax.twinx()
        ax.set_zorder(px.get_zorder() + 1)   # bars and callouts above the price lines
        ax.patch.set_visible(False)
        for label, g in d.groupby("label"):
            px.step(g.time, g.price, where="post", lw=1.2, label=label)
        px.set_ylabel("price")
        ax.legend(*px.get_legend_handles_labels(), fontsize=7, loc="center left", framealpha=.8)
        if annotate and len(flow):
            ax.set_ylim(0, flow.max() / 1e3 * 2.1)
            b = bursts_by_market(d, ev.bursts).sort_values("t_ms")
            top = pd.concat([b.head(1), b.iloc[1:].nlargest(annotate - 1, "usd")]).sort_values("t_ms") if len(b) else b
            many = d.label.nunique() > 1
            for i, burst in enumerate(top.itertuples()):
                x = ts(burst.t_ms)
                y = flow.get(burst.t_ms // bucket_ms * bucket_ms, burst.usd) / 1e3
                frac = (burst.t_ms - t0) / (t1 - t0)
                ax.annotate(callout(pd.Series(burst._asdict()), venue, burst.label if many else None), (x, y),
                            xytext=(x, 0.97 if i % 2 == 0 else 0.68), textcoords=("data", "axes fraction"),
                            ha="left" if frac < 0.15 else "right" if frac > 0.85 else "center", va="top", fontsize=7.5,
                            bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "0.6", "alpha": 0.9},
                            arrowprops={"arrowstyle": "-", "color": "0.4", "lw": 0.8})
    for i, ax in enumerate(axes):
        for name, t in ev.marks.items():
            ax.axvline(ts(t), color="k", ls=":", lw=1)
            if i == 0 and t0 <= t <= t1:
                ax.annotate(name, (ts(t), 0), xycoords=("data", "axes fraction"), xytext=(2, 2), textcoords="offset points", fontsize=7, rotation=90, va="bottom")
        if first_hl is not None and pd.notna(first_hl):
            ax.axvline(ts(first_hl), color="tab:red", ls="--", lw=1)
        ax.set_xlim(ts(t0), ts(t1))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=ev.tz))
    fig.suptitle(f"{ev.title}. Red dashed: first Hyperliquid burst; dotted: " + ", ".join(ev.marks) + f". Times UTC{ev.tz.utcoffset(None).total_seconds() / 3600:+g}.", fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    return fig


def overlay(tape: pd.DataFrame, ev, t0: int, t1: int):
    """Hyperliquid over the prediction markets on one clock.
    Top: YES prices (left, ¢) with the HL perp's % move from its last pre-release trade (right).
    Bottom: each venue's cumulative YES/long taker buying as % of its total in the window, so venues of
    very different size compare on when the buying happened. The event's release mark is t=0."""
    def ts(t):
        x = pd.to_datetime(t, unit="ms", utc=True)
        return x.dt.tz_convert(ev.tz) if isinstance(x, pd.Series) else x.tz_convert(ev.tz)

    release = ev.release
    t_rel = ev.marks[release] if release else t0
    d = tape[tape.t_ms.between(t0, t1)]
    fig, (top, bot) = plt.subplots(2, 1, figsize=(17, 9), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    style = {"kalshi": {"ls": "-"}, "polymarket": {"ls": "--"}, "pascal": {"ls": ":", "marker": "o", "ms": 4}}
    for (venue, label), g in d[d.venue != "hyperliquid"].groupby(["venue", "label"]):
        if len(g) > 1:
            top.step(g.time, g.price * 100, where="post", lw=1.3, label=label, **style.get(venue, {}))
    top.set_ylabel("YES price (¢)")
    hl_ax = top.twinx()
    for coin, g in tape[tape.venue == "hyperliquid"].groupby("label"):
        base = g[g.t_ms < t_rel].price.iloc[-1]
        w = g[g.t_ms.between(t0, t1)]
        hl_ax.step(w.time, (w.price / base - 1) * 100, where="post", color="black", lw=2, label=f"{coin} % vs pre-release ({base:g})")
    hl_ax.set_ylabel("Hyperliquid move (%)")
    h1, l1 = top.get_legend_handles_labels()
    h2, l2 = hl_ax.get_legend_handles_labels()
    top.legend(h2 + h1, l2 + l1, fontsize=8, loc="upper left", bbox_to_anchor=(1.05, 1), borderaxespad=0, framealpha=.9)
    top.set_title("Prices: prediction-market YES (colored, left axis) vs Hyperliquid perp (black, right axis)", loc="left", fontsize=10)

    colors = {"hyperliquid": "black", "kalshi": "tab:green", "polymarket": "tab:blue", "pascal": "tab:purple"}
    firsts = bursts_by_market(d, ev.bursts).groupby("venue").t_ms.min()
    for venue, g in d[d.side > 0].groupby("venue"):
        cum = g.usd.cumsum() / g.usd.sum() * 100
        first = f"first burst {(firsts[venue] - t_rel) / 1000:+.1f} s" if venue in firsts else "no burst"
        bot.step(g.time, cum, where="post", color=colors.get(venue), lw=2, label=f"{venue}: \\${_k(g.usd.sum())} total; {first}")
    bot.set_ylabel("cumulative taker buying (% of window total)")
    bot.set_ylim(0, 100)
    bot.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.05, 1), borderaxespad=0, framealpha=.9)
    bot.set_title("When the buying happened: each venue's YES/long taker $ accumulated over the window", loc="left", fontsize=10)
    for ax in (top, bot):
        for name, t in ev.marks.items():
            ax.axvline(ts(t), color="tab:red" if name == release else "0.3", ls="--" if name == release else ":", lw=1.2)
            if ax is top and t0 <= t <= t1:
                ax.annotate(f"{name} {ts(t).strftime('%H:%M:%S.%f')[:-5]}", (ts(t), 1), xycoords=("data", "axes fraction"),
                            xytext=(3, -3), textcoords="offset points", fontsize=8, rotation=90, va="top")
        ax.set_xlim(ts(t0), ts(t1))
    bot.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=ev.tz))
    fig.suptitle(f"{ev.title}: Hyperliquid overlaid on the prediction markets. Times UTC{ev.tz.utcoffset(None).total_seconds() / 3600:+g}.", fontsize=10)
    fig.tight_layout()
    return fig
