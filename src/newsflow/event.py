"""Event configs (events/*.toml): the window, markets and reference timestamps of one study."""
import pathlib
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


@dataclass(frozen=True)
class Event:
    name: str
    title: str
    start_ms: int
    end_ms: int
    tz: timezone
    marks: dict[str, int]
    release: str | None          # the mark that is the news going public (t=0 in the overlay)
    hl_coins: list[str]
    hl_source: str
    kalshi: dict[str, str]       # ticker -> label
    polymarket: dict[str, str]   # event slug -> label prefix
    bursts: dict[str, tuple[int, float]]  # venue -> (bucket ms, min taker-buy $ per bucket)


def load(path: str | pathlib.Path) -> Event:
    c = tomllib.loads(pathlib.Path(path).read_text())
    hl = c.get("hyperliquid", {})
    return Event(
        name=c["name"], title=c["title"], start_ms=ms(c["start"]), end_ms=ms(c["end"]),
        tz=timezone(timedelta(hours=c["utc_offset"])),
        marks={k: ms(v) for k, v in c.get("marks", {}).items()}, release=c.get("release"),
        hl_coins=hl.get("coins", []), hl_source=hl.get("source", "ironflow"),
        kalshi=c.get("kalshi", {}), polymarket=c.get("polymarket", {}),
        bursts={k: (int(v[0]), float(v[1])) for k, v in c["bursts"].items()},
    )
