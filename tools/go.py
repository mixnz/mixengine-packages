#!/usr/bin/env python3
"""Borrow a Go distribution from go.dev and repack it as a MixEngine artifact.

**The runtime that asks for nothing to be built.** Upstream publishes one relocatable archive per
cell, for all six cells, and one JSON document that names every file with its SHA-256. The `go`
command has derived `GOROOT` from its own location since 1.10, so nothing is relocated either: the
whole job is to fetch, verify, take out what nothing a user runs reads, prove it, and pack.

**The floor is 1.21, and it is this repository's rather than upstream's.** From 1.21 every release
is `go1.N.P`; below it the first release of a line is `go1.20`, which is not a version this index
can sort as a patch of its line. 1.21 is also the release that gave the `go` command `GOTOOLCHAIN`,
which is what decides whether pinning a version means anything — see docs/packages/go.md.

**What goes is decided by what reads it, and measured on 1.27.1 before it was written.** `api/` is
read by `cmd/api` and `test/` by `go tool dist test`, both only while Go tests itself; `doc/` is the
specification as HTML. The `src/**/testdata` directories are the standard library's own test
fixtures, and 30 of the 53 binaries inside them carry DWARF — which `borrow.publish` refuses, and
which `strip.debug` would "fix" by rewriting upstream's fixtures. `misc/` stays: before 1.24 it holds
`misc/wasm/go_js_wasm_exec`.

**`go.env` is upstream's, byte for byte**, including `GOTOOLCHAIN=auto`. The daemon renders
`GOTOOLCHAIN=local` into a project's environment; an archive edited to say so would be a Go that
behaves unlike the version it names.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import eol  # noqa: E402
import relocate  # noqa: E402
import strip  # noqa: E402

CATALOGUE = "https://go.dev/dl/?mode=json&include=all"
DOWNLOAD = "https://go.dev/dl"

# (os, arch) -> upstream's GOOS, GOARCH, and the archive suffix. GOOS/GOARCH are also the name of
# the tool directory, `pkg/tool/<goos>_<goarch>`, which is where half of the machine code lives.
TARGETS = {
    ("windows", "x86_64"): ("windows", "amd64", "zip"),
    ("windows", "aarch64"): ("windows", "arm64", "zip"),
    ("macos", "aarch64"): ("darwin", "arm64", "tar.gz"),
    ("macos", "x86_64"): ("darwin", "amd64", "tar.gz"),
    ("linux", "x86_64"): ("linux", "amd64", "tar.gz"),
    ("linux", "aarch64"): ("linux", "arm64", "tar.gz"),
}

FLOOR = (1, 21)

# `go1.27.1` and nothing else: `go1.27rc3` is a release candidate, and `go1.20` is a line's first
# release from before the three-part naming, which the floor already excludes.
STABLE = re.compile(r"go(\d+\.\d+\.\d+)")

# Removed at the root. Each is read only while Go builds or tests itself — measured by searching
# every non-test `.go` file of 1.27.1 for a path joining GOROOT to it, and finding none.
REMOVED_ROOT = ("api", "test", "doc")

LAYOUT = {
    "windows": {"go": "bin/go.exe", "gofmt": "bin/gofmt.exe"},
    "unix": {"go": "bin/go", "gofmt": "bin/gofmt"},
}


def resolve(spec: str, target: tuple[str, str]) -> tuple[str, str, str]:
    """Turn ``1.27``, ``1.27.1`` or ``latest`` into ``(version, filename, sha256)`` for this cell.

    The version, the file and the digest all come out of one entry of one document, so the digest
    can never be read for a different file than the one downloaded.

    A spec below the floor is a refusal, not an empty cell: nothing upstream is missing, this
    repository has decided not to offer it, and exit 75 would tell the workflow otherwise.
    """
    asked: tuple[int, ...] = ()
    if spec != "latest":
        asked = borrow.parts(spec)
        if len(asked) < 2 or asked[:2] < FLOOR:
            raise SystemExit(
                f"MixEngine offers Go {FLOOR[0]}.{FLOOR[1]} and newer; {spec!r} is not. Below 1.21 "
                f"a release is not a three-part version and the go command has no GOTOOLCHAIN — "
                f"see tools/go.py"
            )

    goos, goarch, suffix = TARGETS[target]
    offered: dict[tuple[int, ...], tuple[str, str, str]] = {}
    lines: set[str] = set()
    for release in json.loads(borrow.fetch(CATALOGUE)):
        match = STABLE.fullmatch(release.get("version", ""))
        if not release.get("stable") or not match:
            continue
        version = match.group(1)
        if borrow.parts(version)[:2] < FLOOR:
            continue
        lines.add(".".join(version.split(".")[:2]))
        for entry in release.get("files", ()):
            if (entry.get("kind"), entry.get("os"), entry.get("arch")) == ("archive", goos, goarch) \
                    and entry["filename"].endswith(f".{suffix}"):
                offered[borrow.parts(version)] = (version, entry["filename"], entry["sha256"])

    candidates = sorted(key for key in offered if key[: len(asked)] == asked)
    if not candidates:
        exists = bool(lines) if not asked else any(borrow.parts(line) == asked[:2] for line in lines)
        if exists:
            borrow.unavailable(f"go.dev publishes no {goos}-{goarch} archive for Go {spec}")
        raise SystemExit(
            f"go.dev lists no stable Go {spec}. Lines offered: "
            f"{', '.join(sorted(lines, key=borrow.parts))}"
        )
    return offered[candidates[-1]]


def prune(tree: Path) -> list[str]:
    """Remove what nothing a user runs reads, and answer with what went, as POSIX paths.

    **A delete-list, and not the keep-list `node.py` argues for**, because the argument inverts
    here. Node's surplus sits at the root of a tree of five entries; Go's payload is `src/`, where
    a keep-list would have to name every standard-library package on every line. What is removed is
    instead named by what it is — three root directories, and every directory called `testdata`,
    which is Go's own convention for "read by `go test` and nothing else", so a fixture a future
    line adds is caught without being known.

    Only the outermost `testdata` is named: `upstream.removed` spells a directory by its root, and a
    nested one goes with its parent.
    """
    source = tree / "src"
    doomed = [tree / name for name in REMOVED_ROOT if (tree / name).is_dir()]
    doomed += sorted(
        path for path in source.rglob("testdata")
        if path.is_dir() and "testdata" not in path.relative_to(source).parts[:-1]
    )

    removed: list[str] = []
    freed = 0
    for path in doomed:
        freed += sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
        shutil.rmtree(path)
        removed.append(path.relative_to(tree).as_posix())

    print(f"dropped {len(removed)} paths ({freed:,} bytes)")
    return removed


def describe(
    tree: Path, version: str, target: tuple[str, str], url: str, digest: str,
    removed: list[str], changed: dict[str, str],
) -> dict:
    """What is in the archive, as the daemon will read it.

    *changed* is `strip.debug`'s answer, expected to be empty on every cell; *removed* is
    :func:`prune`'s. Both go through `borrow.declare`, which checks each claim against the tree.
    """
    operating_system, arch = target
    layout = LAYOUT["windows" if operating_system == "windows" else "unix"]
    missing = [name for name, path in layout.items() if not (tree / path).exists()]
    if missing:
        raise SystemExit(
            f"the archive provides no {', '.join(missing)} at "
            f"{', '.join(layout[name] for name in missing)}"
        )

    manifest = {
        "schema": 1,
        "kind": "go",
        "version": version,
        "os": operating_system,
        "arch": arch,
        "source": "borrowed",
        "upstream": {
            "url": url,
            "sha256": digest,
            "verified_against": "go.dev/dl/?mode=json&include=all over HTTPS to the publisher",
        },
        "provides": dict(layout),
    }
    return borrow.declare(tree, manifest, removed=removed, changed=changed)
