"""Minimal JSON-over-HTTP helpers with 429/5xx backoff; stdlib only."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "clob-news-research", "Accept": "application/json"}


def _send(req: urllib.request.Request, tries: int = 6):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise RuntimeError(f"{req.get_method()} {req.full_url}: HTTP {e.code}: {e.read()[:300]!r}") from None
            wait = float(e.headers.get("Retry-After") or 2 ** attempt)
            time.sleep(min(wait, 60))


def get(url: str, params: dict | None = None, headers: dict | None = None):
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return _send(urllib.request.Request(url, headers={**UA, **(headers or {})}))


def post(url: str, body: dict):
    data = json.dumps(body).encode()
    return _send(urllib.request.Request(url, data=data, headers={**UA, "Content-Type": "application/json"}))
