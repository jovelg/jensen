"""data/raw/<event>/: immutable source pulls, gzipped JSON exactly as the APIs returned the records,
with manifest.json recording each file's source, requests, pull time, record count and sha256."""
import gzip
import hashlib
import json
import pathlib
from datetime import datetime, timezone


def path(root: pathlib.Path, name: str) -> pathlib.Path:
    return root / f"{name}.json.gz"


def write(root: pathlib.Path, name: str, data, source: str, requests: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    body = gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0)
    path(root, name).write_bytes(body)
    records = len(data["trades"]) if isinstance(data, dict) and "trades" in data else len(data)
    manifest = root / "manifest.json"
    entries = json.loads(manifest.read_text()) if manifest.exists() else {}
    entries[path(root, name).name] = {
        "source": source, "requests": requests, "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": records, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
    }
    manifest.write_text(json.dumps(dict(sorted(entries.items())), indent=2) + "\n")


def read(root: pathlib.Path, name: str):
    return json.loads(gzip.decompress(path(root, name).read_bytes()))
