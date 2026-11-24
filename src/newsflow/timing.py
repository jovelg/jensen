"""When did the news actually go out? Helpers for the release-timing evidence of an event.

- GlobeNewswire pages carry the true publish second in `og:article:published_time` / JSON-LD
  `datePublished` (the page shows it truncated to the minute). Scheduled releases land on :00;
  unscheduled ones carry real seconds. GlobeNewswire blocks scripted HTTP clients, so these pages
  are captured with a real browser and stored as raw evidence.
- X post ids are snowflakes: the creation time in ms is in the id itself.
- EDGAR filing index pages show the SEC acceptance time to the second. SEC requires a User-Agent
  that names you (SEC_USER_AGENT="Name email").
"""
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .net import get_text

TWITTER_EPOCH_MS = 1288834974657
EDGAR_TZ = ZoneInfo("America/New_York")
_ACCEPTED = re.compile(r"Accepted</div>\s*<div[^>]*>([\d-]+ [\d:]+)</div>")


def snowflake_ms(post_id: int | str) -> int:
    return (int(post_id) >> 22) + TWITTER_EPOCH_MS


def _edgar_ms(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=EDGAR_TZ).timestamp() * 1000)


def edgar_accepted_ms(index_url: str) -> tuple[int, str]:
    """(acceptance time in ms, the raw 'Accepted' html) from an EDGAR filing index page (times are ET)."""
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise SystemExit("set SEC_USER_AGENT='Your Name you@example.com' (SEC rejects anonymous clients)")
    m = _ACCEPTED.search(get_text(index_url, {"User-Agent": ua}))
    if not m:
        raise RuntimeError(f"no acceptance time on {index_url}")
    return _edgar_ms(m.group(1)), m.group(0)


def release_table(raw: dict) -> list[dict]:
    """Every timing source in a release-timing raw file as {source, t_ms, precision, detail}, in time order."""
    rows = []
    for p in raw["globenewswire"]["pages"]:
        t = datetime.fromisoformat(p["og_article_published_time"].replace("Z", "+00:00"))
        rows.append({"source": f"GlobeNewswire: {p['url'].split('/en/')[-1].removesuffix('.html')[:60]}", "t_ms": int(t.timestamp() * 1000),
                     "precision": "1 s", "detail": p["time_element"]})
    rows.append({"source": "EDGAR 8-K accepted", "t_ms": _edgar_ms(_ACCEPTED.search(raw["edgar_8k"]["accepted_text"]).group(1)),
                 "precision": "1 s", "detail": raw["edgar_8k"]["index_url"]})
    for x in raw["x_posts"]:
        rows.append({"source": f"X post @{x['account']}", "t_ms": snowflake_ms(x["id"]), "precision": "1 ms", "detail": x["url"]})
    return sorted(rows, key=lambda r: r["t_ms"])
