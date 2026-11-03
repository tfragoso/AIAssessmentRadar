"""Persistent history in data/postings.csv: first/last seen, open/closed, weekly snapshots."""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from pathlib import Path

from .models import Posting

CLOSE_AFTER_MISSED = 2


def load(path: Path) -> dict[str, Posting]:
    if not path.exists():
        return {}
    types = {f.name: f.type for f in fields(Posting)}
    out = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            kw = {k: (int(v or 0) if types.get(k) in (int, "int") else v) for k, v in row.items() if k in types}
            p = Posting(**kw)
            out[p.posting_id] = p
    return out


def save(path: Path, postings: dict[str, Posting]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = Posting.csv_fields()
    rows = sorted(postings.values(), key=lambda p: (p.employer, p.first_seen, p.posting_id))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for p in rows:
            d = asdict(p)
            w.writerow({c: d[c] for c in cols})


def merge(
    history: dict[str, Posting],
    current: list[Posting],
    run_date: str,
    ok_employers: set[str],
    new_run: bool = True,
) -> tuple[list[Posting], list[Posting]]:
    """Fold this run's postings into history in place. Returns (new, closed_now).

    Postings of employers whose source failed this run are left untouched. A posting closes after
    being absent from CLOSE_AFTER_MISSED successful runs. new_run=False (a re-run on the same day)
    does not count another miss."""
    new, closed = [], []
    seen = set()
    for p in current:
        seen.add(p.posting_id)
        old = history.get(p.posting_id)
        if old is None:
            p.first_seen = run_date
            new.append(p)
        else:
            p.first_seen = old.first_seen
        p.last_seen, p.status, p.missed_runs = run_date, "open", 0
        history[p.posting_id] = p

    for pid, p in history.items():
        if pid in seen or p.status != "open" or p.employer not in ok_employers:
            continue
        if new_run:
            p.missed_runs += 1
        if p.missed_runs >= CLOSE_AFTER_MISSED:
            p.status = "closed"
            closed.append(p)
    return new, closed


def write_snapshot(path: Path, history: dict[str, Posting]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = sorted(pid for pid, p in history.items() if p.status == "open")
    path.write_text("posting_id\n" + "".join(f"{i}\n" for i in ids), encoding="utf-8")


def write_descriptions(folder: Path, postings: list[Posting]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for p in postings:
        if p.description:
            (folder / f"{p.posting_id}.txt").write_text(f"{p.title}\n{p.url}\n\n{p.description}\n", encoding="utf-8")
