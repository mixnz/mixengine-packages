#!/usr/bin/env python3
"""Compile Valkey from upstream source, the Redis row's BSD continuation.

**Why this row exists.** The Redis row's floor is 7.2 because 7.2 is the last BSD-3 Redis; 7.4 is
RSALv2/SSPLv1 and 8.0 adds AGPLv3. Valkey forked from Redis 7.2.4 in March 2024 and is BSD-3-Clause
on every line, so it is where a user who needs a permissive in-memory store past 7.2 goes. It is its
own kind rather than a substitute inside `redis`: P8 refused Valkey as a way to fill Redis's Windows
cell, and that refusal was right — one version cannot mean two programs.

**The build is Redis's, and so is the code that knows how.** Finding Cygwin and proving it is Cygwin,
running a script under it with its own tools on `PATH`, reading `DEPENDENCY_TARGETS` out of the
tarball, the two compiler flags Cygwin's headers need — all of that is imported from `redis.py`, so
one runtime's quirks live in one file. What is Valkey's is here: the names, `USE_REDIS_SYMLINKS=no`,
the licence table, and a smoke test that asks for `valkey_version` rather than the `redis_version`
every line also reports for client compatibility.

**Core only, no TLS, no RDMA** — the Redis row's choices for the Redis row's reasons, repeated so the
two rows answer the same questions the same way.

**The version and its digest come from one document**: `valkey-io/valkey-hashes`, upstream's catalogue
in exactly `redis-hashes`' format, one `hash <file> sha256 <digest> <url>` line per tarball.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import redis  # noqa: E402
import relocate  # noqa: E402
import strip  # noqa: E402

HASHES = "https://raw.githubusercontent.com/valkey-io/valkey-hashes/main/README"

# Named for the same reason `redis.py` names itself: a publisher entitled to block a default agent is
# entitled to know which program is asking instead.
AGENT = redis.AGENT

# The oldest line: the one Valkey forked, and still patched upstream.
FLOOR = (7, 2)


def catalogue() -> dict[tuple[int, ...], tuple[str, str, str]]:
    """Every stable release upstream has published, as ``version -> (version, url, sha256)``.

    Release candidates (``valkey-9.2.0-rc1.tar.gz``) share the file and are not releases, so the
    pattern insists on three numeric components.
    """
    listing = borrow.fetch(HASHES, headers=AGENT).decode("utf-8", "replace")
    offered: dict[tuple[int, ...], tuple[str, str, str]] = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] != "hash" or fields[2] != "sha256":
            continue
        match = re.fullmatch(r"valkey-(\d+\.\d+\.\d+)\.tar\.gz", fields[1])
        if not match:
            continue
        key = borrow.parts(match.group(1))
        if key[:2] < FLOOR:
            continue
        url = fields[4]
        if not url.startswith("https://"):
            url = "https://" + url.partition("://")[2]
        offered[key] = (match.group(1), url, fields[3])
    if not offered:
        raise SystemExit(f"{HASHES} listed no valkey-<x.y.z>.tar.gz at all; upstream changed its shape")
    return offered


def resolve(spec: str) -> tuple[str, str, str]:
    """Turn ``9``, ``9.1``, ``9.1.2`` or ``latest`` into one published tarball and its digest."""
    offered = catalogue()
    if spec == "latest":
        candidates = sorted(offered)
    else:
        prefix = borrow.parts(spec)
        candidates = sorted(key for key in offered if key[: len(prefix)] == prefix)
    if not candidates:
        lines = [".".join(map(str, line)) for line in sorted({key[:2] for key in offered})]
        raise SystemExit(
            f"valkey-hashes lists no stable {spec} at or above {'.'.join(map(str, FLOOR))}. "
            f"It offers {', '.join(lines)}."
        )
    return offered[candidates[-1]]


def source(spec: str, work: Path) -> tuple[str, Path, str, str]:
    """Fetch and unpack the release tarball, checked against the digest the catalogue states."""
    version, url, digest = resolve(spec)
    if version != spec:
        print(f"{spec} resolves to Valkey {version}")

    tarball = work / f"valkey-{version}.tar.gz"
    print(f"fetching {url}")
    tarball.write_bytes(borrow.fetch(url, timeout=1800, headers=AGENT))
    actual = borrow.sha256(tarball)
    if actual != digest:
        raise SystemExit(f"{tarball.name} hashes to {actual}, valkey-hashes states {digest}")
    print(f"sha256 {actual} (verified against valkey-io/valkey-hashes)")

    with tarfile.open(tarball) as archive:
        archive.extractall(work, filter="data")
    unpacked = work / f"valkey-{version}"
    if not (unpacked / "src" / "Makefile").is_file():
        raise SystemExit(f"{unpacked} has no src/Makefile; this is not a Valkey release tarball")
    return version, unpacked, actual, url
