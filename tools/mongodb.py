#!/usr/bin/env python3
"""Borrow a MongoDB server build from mongodb.org and repack it as a MixEngine artifact.

**The row that existed as half a promise.** Every PHP this repository publishes carries the
``mongodb`` extension, on every branch and every cell, because ``php_legacy_unix.py`` fails a build
without it — *"MixEngine offers {package} on every version it ships, so an artifact without it is
not one worth publishing"*. Nothing here installed a MongoDB for it to talk to. This is that half.

The floor is **6.0**, and it is upstream's rather than a preference. Two lines below it were
abandoned on macOS while they were still being patched — ``4.4.29`` and ``5.0.31`` publish a
``macos-x86_64`` tarball and ``4.4.31`` and ``5.0.34`` publish no macOS asset at all — and macOS on
Apple Silicon starts at 6.0. Filling those cells would mean compiling MongoDB on macOS for a line
upstream has given up on there, which is the MySQL 5.6/5.7 shape at a higher price.

**Which lines exist is read off upstream's catalogue rather than written down here.** A release is
offered when it is flagged ``production_release`` *and* ``lts_release``; the rapid releases between
the LTS ones carry ``continuous_release``, live a few months, and are not something a blueprint
should be able to pin.

**Windows on ARM is upstream's empty cell.** No MongoDB has ever been built for it, at any version,
so that cell states itself through ``borrow.unavailable`` rather than being written down here and
going stale.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package

# The newest release of every line, 400 KB, which is what a `--version 8.3` run needs. `full.json`
# is 50 MB and holds every patch ever published; it is fetched only when an exact older version is
# asked for and `current.json` does not have it.
CURRENT = "https://downloads.mongodb.org/current.json"
FULL = "https://downloads.mongodb.org/full.json"

# (os, arch) -> upstream's `target` spelling, and the archive suffix.
#
# Linux is the one cell whose target is not a constant: upstream builds per distribution and the
# builds differ in which OpenSSL they expect. `linux_download` decides it by measurement.
TARGETS = {
    ("windows", "x86_64"): ("windows", "zip"),
    ("macos", "aarch64"): ("macos", "tgz"),
    ("macos", "x86_64"): ("macos", "tgz"),
    ("linux", "x86_64"): ("linux", "tgz"),
    ("linux", "aarch64"): ("linux", "tgz"),
}

# Upstream's spelling for an architecture, per target. macOS says `arm64` where this repository says
# `aarch64`, and Linux says `aarch64` like everybody else.
ARCH = {
    "macos": {"aarch64": "arm64", "x86_64": "x86_64"},
    "windows": {"x86_64": "x86_64"},
    "linux": {"aarch64": "aarch64", "x86_64": "x86_64"},
}

# **The floor is this repository's decision and the catalogue cannot make it.** The design this
# recipe was written from claimed that `production_release` and `lts_release` together select the
# five lines offered here; measured against `current.json`, they select seven — upstream flags 5.0
# and 4.4 as LTS production releases too, and goes on publishing patches for them. The two flags do
# the half they can do, which is telling an LTS line from the rapid releases between them, and this
# says the rest: below 6.0 a line cannot be offered *whole*, because upstream withdrew macOS from
# both while they were still being patched. `4.4.29` and `5.0.31` publish a `macos-x86_64` tarball;
# `4.4.31` and `5.0.34` publish no macOS asset of any kind. Offering them would mean either
# compiling MongoDB on macOS for a line upstream has abandoned there, or publishing two lines that
# quietly mean less than the five above them.
FLOOR = (6, 0)


def catalogue(exact: bool) -> list[dict]:
    """Upstream's release records, newest first.

    *exact* asks for the full catalogue, which is fifty megabytes and the only place a patch older
    than a line's newest is listed.
    """
    url = FULL if exact else CURRENT
    document = json.loads(borrow.fetch(url))
    return document["versions"]


def offered(records: list[dict]) -> dict[str, dict]:
    """Offered line -> its newest record: an LTS production release at or above `FLOOR`.

    Two conditions rather than one, because they answer different questions. Upstream's flags say
    which lines are LTS at all — that is a fact about upstream's schedule and it would go stale if
    it were written down here. `FLOOR` says which of those can be offered on six cells, which is a
    fact about what upstream *built*, and upstream states it nowhere.
    """
    found: dict[str, dict] = {}
    for record in records:
        if not (record.get("production_release") and record.get("lts_release")):
            continue
        parts = tuple(int(number) for number in record["version"].split(".")[:2])
        if parts < FLOOR:
            continue
        found.setdefault(".".join(str(number) for number in parts), record)
    return found


def download_for(record: dict, target: tuple[str, str]) -> dict | None:
    """The ``base`` edition download for this cell, or None where upstream built none."""
    _, arch = target
    upstream_target, _suffix = TARGETS[target]
    want = ARCH[upstream_target][arch]
    for download in record["downloads"]:
        if download.get("edition") != "base":
            continue
        if download.get("target") != upstream_target or download.get("arch") != want:
            continue
        return download
    return None


def refuse(spec: str, lines: dict[str, dict]) -> None:
    """End the run saying why this line is not on offer, which is two different sentences."""
    try:
        parts = tuple(int(number) for number in spec.split(".")[:2])
    except ValueError:
        parts = ()

    if parts and parts < FLOOR:
        raise SystemExit(
            f"MongoDB {'.'.join(str(n) for n in parts)} is below this repository's floor of "
            f"{FLOOR[0]}.{FLOOR[1]}. Upstream still patches it and still calls it LTS, and it "
            "cannot be offered whole: macOS was withdrawn from 4.4 and 5.0 while both were alive, "
            "so the newest patch of either has no macOS build at all. See docs/packages/mongodb.md."
        )
    raise SystemExit(
        f"MongoDB {spec} is not a line this repository offers. Offered: "
        f"{', '.join(sorted(lines))}. A line is offered when upstream flags it production_release "
        "and lts_release and it is at or above the floor; adding one is a roadmap entry rather "
        "than an input."
    )


def resolve(spec: str, target: tuple[str, str]) -> tuple[str, dict]:
    """Turn ``8.3``, ``8.3.11`` or ``latest`` into one published archive for this cell."""
    if target not in TARGETS:
        borrow.unavailable(
            f"MongoDB has never been built for {target[0]}/{target[1]} — no version of it, "
            "at any line. This cell is upstream's, not this repository's."
        )

    exact = spec.count(".") >= 2
    lines = offered(catalogue(exact=exact))

    if spec == "latest":
        record = lines[max(lines, key=lambda line: tuple(int(n) for n in line.split(".")))]
    elif spec in lines:
        record = lines[spec]
    elif exact:
        line = ".".join(spec.split(".")[:2])
        if line not in lines:
            refuse(line, lines)
        record = next(
            (r for r in catalogue(exact=True)
             if r["version"] == spec and r.get("production_release")),
            None,
        )
        if record is None:
            raise SystemExit(f"upstream lists no production release {spec}")
    else:
        refuse(spec, lines)

    download = download_for(record, target)
    if download is None:
        borrow.unavailable(
            f"upstream published no {target[0]}/{target[1]} build of MongoDB "
            f"{record['version']}; nothing to borrow for this cell."
        )
    return record["version"], download
