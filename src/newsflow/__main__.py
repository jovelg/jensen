"""python -m newsflow {fetch,process,figures,all} events/<event>.toml"""
import argparse

import matplotlib

matplotlib.use("Agg")

from . import pipeline  # noqa: E402
from .event import load  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(prog="newsflow", description=__doc__)
    p.add_argument("step", choices=["fetch", "process", "figures", "all"])
    p.add_argument("event", help="events/<name>.toml")
    a = p.parse_args()
    ev = load(a.event)
    for step in (["fetch", "process", "figures"] if a.step == "all" else [a.step]):
        getattr(pipeline, step)(ev)


if __name__ == "__main__":
    main()
