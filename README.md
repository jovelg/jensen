# news-research

Cross-venue taker tapes around news: Hyperliquid, Kalshi, Polymarket (polymarket.com) and Polymarket US.

- `notebooks/jensen_reinstatement.ipynb`: who clicked first when NVIDIA reinstated Jensen Huang (2026-11-23, 8:55 AM ET). Executed outputs are saved; the source pulls are cached in `data/2026-11-23-jensen/`, so it re-runs offline.
- `src/hl.py`: Hyperliquid market discovery, candles, tick fills (Ironflow; S3 archive).
- `src/venues.py`: Kalshi, Polymarket and Polymarket US tapes in one row format.
- `src/event_window.py`: CLI that writes `trades.csv`, `bursts.txt` and `chart.png` for any window.

```sh
uv run --with jupyter,pandas,matplotlib jupyter lab notebooks/jensen_reinstatement.ipynb
```

Polymarket US publishes no trade history; its trades exist only if captured live from the markets websocket.
