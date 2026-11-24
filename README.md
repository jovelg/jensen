# news-research

cross-venue taker tapes for that time when Jensen Huang got reinstated as the CEO of $NVDA twelve days after resigning
- tradexyz @ hyperliquid
- kalshi
- polymarket

## findings
| Event | Finding |
|---|---|
| [2026-11-23: Jensen Huang reinstated as NVIDIA CEO](reports/jensen.md) | GlobeNewswire published at 8:55:41 ET (page shows "08:55"). `xyz:NVDA` long-taker BUY hit in the same second; Kalshi's first burst 7.4s after the release, first X posts 10.5s, Polymarket's first burst 12s (a $34 fill at 9s).

## layout
```
events/              one TOML per event: window, markets, reference timestamps, burst thresholds
src/newsflow/        library: one module per venue (fetch raw + normalize), pipeline, analysis, CLI
data/raw/<event>/    source pulls, records unmodified (gzipped JSON) + manifest.json (source, requests, pull time, sha256)
data/processed/      normalized tape and burst tables (CSV)
notebooks/           numbered evidence notebooks; outputs are committed so GitHub renders them
reports/             written findings; reports/figures/ holds their charts
```

## reproduce
needs [uv](https://docs.astral.sh/uv/). dependencies pinned in `uv.lock`.

```sh
make all                                    # fetch -> process -> figures -> notebooks
make all EVENT=events/<name>.toml           # another event
```

`make data` never refetches an existing raw file; delete one to force it. Venue data limits:

| Venue | History available after the fact |
|---|---|
| Kalshi | full public tape; trades older than the archive cutoff come from `/historical/trades` |
| Polymarket | full on-chain tape (block time, ~1–3 s after the match) |
| Pascal | full public tape: matching-engine ms timestamps, explicit taker side, maker and taker wallets; no key. Supported (`[pascal]` in an event config); left out of the Jensen study because its books were too thin to matter (4 trades in the window) |
| Hyperliquid | Ironflow (third-party indexer): each pull cross-matched against Hyperliquid's candles and per-wallet fills (`newsflow.verify`). S3 archive (`hyperliquid.source = "s3"`): first-party, carries the taker flag; AWS credentials needed, `aws` CLI and `lz4` |
