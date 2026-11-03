"""The weekly run: fetch -> normalize -> filter -> enrich -> merge -> render."""

from __future__ import annotations

import csv
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from pathlib import Path

from . import history
from .adapters import REGISTRY, Context
from .config import Config
from .enrich import rules
from .filter import FamilyMatcher, apply
from .http import Client
from .models import Posting
from .normalize import RegionTagger, to_posting
from .render.tables import SourceStatus, render_readme, write_csvs

log = logging.getLogger(__name__)

UNCOVERED_ATS = {"unknown", "none", "blocked", "manual-only"}


def source_name(emp: dict) -> str:
    return emp.get("source") or emp["name"]


def fetch_all(cfg: Config, client: Client, only: str | None = None):
    tagger = RegionTagger(cfg.regions)
    matcher = FamilyMatcher(cfg.families)
    ctx = Context(
        client=client,
        search_terms=cfg.keywords.get("search_terms", []),
        title_match=lambda t: matcher.title_family(t) is not None,
        maybe_match=matcher.maybe,
        is_swiss=tagger.is_swiss,
    )
    kept: dict[str, Posting] = {}
    statuses: list[SourceStatus] = []
    uncovered: list[dict] = []
    jobs = []
    for emp in cfg.employers:
        if only and only.lower() not in emp["name"].lower():
            continue
        if emp.get("ats", "unknown") in UNCOVERED_ATS:
            uncovered.append(emp)
        else:
            jobs.append(emp)

    def fetch_one(emp: dict):
        ats = emp["ats"]
        st = SourceStatus(source=source_name(emp), employer=emp["name"], ats=ats, ok=False)
        adapter = REGISTRY.get(ats)
        if adapter is None:
            st.error = f"no adapter '{ats}'"
            return emp, st, []
        try:
            return emp, st, adapter(emp, ctx)
        except Exception as e:  # a broken source must not stop the run
            st.error = f"{type(e).__name__}: {e}"[:300]
            return emp, st, []

    # Sources run in parallel; the client still throttles each host to one request per second.
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_one, jobs))

    for emp, st, raws in results:  # in config order, so outputs are deterministic
        statuses.append(st)
        if st.error:
            log.warning("%s failed: %s", st.source, st.error)
            continue
        st.ok, st.fetched = True, len(raws)
        for raw in raws:
            p = to_posting(raw, emp, tagger)
            if p.region == "Abroad" and not emp.get("fetch_abroad"):
                continue
            if not apply(p, matcher):
                continue
            rules.enrich(p, raw, emp)
            if p.posting_id not in kept:
                kept[p.posting_id] = p
                st.kept += 1
        log.info("%-28s %-15s fetched %4d kept %3d", st.source, st.ats, st.fetched, st.kept)
    return list(kept.values()), statuses, uncovered


def _previous_run(status_csv: Path) -> str:
    if not status_csv.exists():
        return ""
    with status_csv.open(encoding="utf-8") as fh:
        dates = [r["date"] for r in csv.DictReader(fh)]
    return max(dates) if dates else ""


def _write_status(status_csv: Path, run_date: str, statuses: list[SourceStatus]) -> None:
    cols = ["date", "source", "employer", "ats", "ok", "fetched", "kept", "error"]
    rows = []
    if status_csv.exists():
        with status_csv.open(encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r["date"] != run_date]
    rows += [{"date": run_date, **asdict(s)} for s in statuses]
    with status_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def run(cfg: Config, out: Path, run_date: str | None = None, only: str | None = None, offline: bool = False,
        dry_run: bool = False) -> int:
    run_date = run_date or date.today().isoformat()
    root = cfg.root
    if dry_run:  # work on a scratch copy of the outputs
        out = root / ".dryrun"
        if (root / "data").exists():
            shutil.copytree(root / "data", out / "data", dirs_exist_ok=True)
    client = Client(cache_dir=root / ".cache" / run_date, offline=offline)
    try:
        current, statuses, uncovered = fetch_all(cfg, client, only)
    finally:
        client.close()

    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    status_csv = data / "source_status.csv"
    prev = _previous_run(status_csv)
    hist = history.load(data / "postings.csv")
    ok = {s.employer for s in statuses if s.ok}  # only these employers' missing postings age
    new, closed = history.merge(hist, current, run_date, ok, new_run=run_date != prev)

    history.save(data / "postings.csv", hist)
    history.write_snapshot(data / "snapshots" / f"{run_date}.csv", hist)
    history.write_descriptions(data / "descriptions", current)
    _write_status(status_csv, run_date, statuses)
    write_csvs(out / "csv", hist)
    (out / "README.md").write_text(
        render_readme(hist, cfg.families, run_date, new, closed, statuses, uncovered), encoding="utf-8"
    )

    n_ok = sum(s.ok for s in statuses)
    log.info("run %s: %d/%d sources ok, %d kept, %d new, %d closed -> %s", run_date, n_ok, len(statuses),
             len(current), len(new), len(closed), out)
    return 0


def check(status_csv: Path, min_share: float = 0.5) -> tuple[bool, str]:
    """CI gate: did at least min_share of the sources return data in the latest run?"""
    with status_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    last = max(r["date"] for r in rows)
    latest = [r for r in rows if r["date"] == last]
    ok = [r for r in latest if r["ok"] == "True"]
    failed = [r["source"] for r in latest if r["ok"] != "True"]
    msg = f"{last}: {len(ok)}/{len(latest)} sources ok" + (f"; failed: {', '.join(failed)}" if failed else "")
    return len(ok) >= min_share * len(latest), msg


def failing_twice(status_csv: Path) -> list[str]:
    """Sources that failed in each of the last two runs."""
    with status_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    dates = sorted({r["date"] for r in rows})[-2:]
    if len(dates) < 2:
        return []
    failed = [{r["source"] for r in rows if r["date"] == d and r["ok"] != "True"} for d in dates]
    return sorted(failed[0] & failed[1])
