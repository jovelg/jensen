# news-research

Who trades news first? Cross-venue taker tapes around news events: Hyperliquid perps, Kalshi and Polymarket (polymarket.com). Polymarket US is left out: it publishes no trade tape.

## Findings
| Event | Finding |
|---|---|
| [2026-11-23: Jensen Huang reinstated as NVIDIA CEO](reports/2026-11-23-jensen.md) | Hyperliquid `xyz:NVDA` long-taker buying began at 8:55:41.1 ET, 7.3 s before Kalshi's first burst and 11.9 s before Polymarket's first fill. Whether HL was the trigger needs a set of events. |

## Layout
```
events/              one TOML per event: window, markets, reference timestamps, burst thresholds
src/newsflow/        library: one module per venue (fetch raw + normalize), pipeline, analysis, CLI
data/raw/<event>/    source pulls, records unmodified (gzipped JSON) + manifest.json (source, requests, pull time, sha256)
data/processed/      normalized tape and burst tables (CSV)
notebooks/           numbered evidence notebooks; outputs are committed so GitHub renders them
reports/             written findings; reports/figures/ holds their charts
tests/               normalization and paging rules
```

## Reproduce
Needs [uv](https://docs.astral.sh/uv/). Dependencies are pinned in `uv.lock`.

```sh
make all                                    # fetch -> process -> figures -> notebooks
make all EVENT=events/<name>.toml           # another event
make test
```

`make data` never refetches an existing raw file; delete one to force it. Venue data limits:

| Venue | History available after the fact |
|---|---|
| Kalshi | full public tape; trades older than the archive cutoff come from `/historical/trades` |
| Polymarket | full on-chain taker tape (block time, ~1–3 s after the match) |
| Hyperliquid | Ironflow (third-party indexer): 24 h back without a key. Each pull is checked against Hyperliquid's own candles and per-wallet fills (`newsflow.verify`). S3 archive (`hyperliquid.source = "s3"`): first-party, everything since Jul 2025, carries the taker flag; needs AWS credentials, `aws` CLI and `lz4` |
