"""Command line: jobwatch run | check | failing | probe."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

ATS_SIGNATURES = [
    ("workday", r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:boards|job-boards)(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([a-z0-9]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([a-z0-9-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9.-]+)"),
    ("personio", r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9-]+)"),
    ("prospective", r"ohws\.prospective\.ch/(?:public/v1/medium|careercenter)/(\d+)"),
    ("oracle", r"([a-z0-9]+\.fa\.[a-z0-9]+\.oraclecloud\.com)"),
    ("sfcareer (SuccessFactors)", r"(career\d*\.successfactors\.(?:eu|com)|rmkcdn\.successfactors\.com)"),
    ("refline", r"apply\.refline\.ch/(\d+)"),
    ("umantis", r"(recruitingapp-\d+\.umantis\.com)"),
    ("werecruit", r"careers\.werecruit\.io/[a-z]{2}/([a-z0-9-]+)"),
    ("avature", r"([a-z0-9-]+\.avature\.net)"),
]


def probe(url: str) -> int:
    from .adapters.base import parse_jobposting
    from .http import Client

    c = Client()
    try:
        page = c.get_text(url)
    finally:
        c.close()
    hits = []
    for name, pat in ATS_SIGNATURES:
        for m in sorted(set(re.findall(pat, page)))[:3]:
            hits.append(f"{name}: {m}")
    print("\n".join(hits) or "no known ATS signature found")
    if parse_jobposting(page):
        print("page carries schema.org JobPosting data")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jobwatch")
    ap.add_argument("--root", type=Path, default=Path.cwd(), help="repo root (config/, data/ ...)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch all sources and rebuild outputs")
    r.add_argument("--dry-run", action="store_true", help="write outputs to .dryrun/ instead of the repo")
    r.add_argument("--only", help="only employers whose name contains this text")
    r.add_argument("--offline", action="store_true", help="use only the run cache, no network")
    r.add_argument("--date", help="run date (YYYY-MM-DD), default today")
    c = sub.add_parser("check", help="exit 1 if fewer than half the sources returned data in the last run")
    c.add_argument("--min-share", type=float, default=0.5)
    sub.add_parser("failing", help="print sources that failed in each of the last two runs")
    p = sub.add_parser("probe", help="guess which ATS a careers page uses")
    p.add_argument("url")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    from . import pipeline
    from .config import load

    root = args.root.resolve()
    if args.cmd == "run":
        return pipeline.run(load(root), root, args.date, args.only, args.offline, args.dry_run)
    if args.cmd == "check":
        ok, msg = pipeline.check(root / "data" / "source_status.csv", args.min_share)
        print(msg)
        return 0 if ok else 1
    if args.cmd == "failing":
        print("\n".join(pipeline.failing_twice(root / "data" / "source_status.csv")))
        return 0
    if args.cmd == "probe":
        return probe(args.url)
    return 2


if __name__ == "__main__":
    sys.exit(main())
