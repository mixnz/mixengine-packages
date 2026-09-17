#!/usr/bin/env python3
"""Borrow a JDK from Microsoft Build of OpenJDK and repack it as a MixEngine artifact.

**Microsoft, and not the build everybody names.** Eclipse Temurin publishes a Windows ARM64 JDK on
one LTS line, from 21.0.5, and none on 11, 17 or 25; filling those cells from a second vendor would
put two builds under one version number, which is the MariaDB lesson. Microsoft publishes all six
cells on all four LTS lines from one build system, so this row has one publisher and no empty cell.

**The catalogue is Microsoft's own entry in the Adoptium Marketplace**, which serves the data each
vendor submits (`microsoft/openjdk-adoptium-marketplace-data`). It names every release Microsoft has
shipped on a line, identically for all six cells, with a SHA-256 per archive — and Microsoft publishes
a `.sha256sum.txt` beside each archive too, so the digest is checked against both.

**The version is Microsoft's file name.** The first release of 25 is `jdk-25+36` in `release_name`
and `microsoft-jdk-25.0.0-linux-x64.tar.gz` as a file; the index needs the second.

**What goes is what no process in the JDK reads**, measured before this was written: the 50 MB
`lib/src.zip` an IDE reads, the JNI `include/` a C compiler reads, the `lib/*.lib` import libraries a
linker reads, and the `man/` pages the Unix cells of 11 and 17 carry. `jmods/` stays, because `jlink`
reads it and `jlink` is in the archive.

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

RELEASES = "https://api.adoptium.net/v3/info/available_releases"
MARKETPLACE = "https://marketplace-api.adoptium.net/v1/assets/feature_releases/microsoft"

# api.adoptium.net answers 403 to `Python-urllib/3.x`, as download.redis.io and php.net do, and to a
# named agent it answers 200 — so this recipe says which program is asking, in the same words.
AGENT = {"User-Agent": "mixengine-packages (+https://github.com/mixnz/mixengine-packages)"}

# (os, arch) -> the Marketplace's spelling of both, Microsoft's spelling in the file name, and the
# archive suffix. The two spellings differ only for macOS: `mac` in the query, `macos` in the file.
TARGETS = {
    ("windows", "x86_64"): ("windows", "x64", "windows", "zip"),
    ("windows", "aarch64"): ("windows", "aarch64", "windows", "zip"),
    ("macos", "aarch64"): ("mac", "aarch64", "macos", "tar.gz"),
    ("macos", "x86_64"): ("mac", "x64", "macos", "tar.gz"),
    ("linux", "x86_64"): ("linux", "x64", "linux", "tar.gz"),
    ("linux", "aarch64"): ("linux", "aarch64", "linux", "tar.gz"),
}

# The oldest LTS line Microsoft builds. 8 is an LTS line too, and Microsoft points to Temurin for it.
FLOOR = 11


def lines() -> list[int]:
    """The LTS lines at or above the floor, newest last, as Adoptium's release document states them.

    Read rather than written down, so the next LTS line is offered the day upstream calls it one; a
    line Microsoft has not shipped yet is refused by :func:`catalogue`, with that reason.
    """
    stated = json.loads(borrow.fetch(RELEASES, headers=AGENT))["available_lts_releases"]
    return sorted(line for line in stated if line >= FLOOR)


def catalogue(line: int, target: tuple[str, str]) -> list[dict]:
    """Every release Microsoft lists on *line* for this cell, as ``{version, release, url, sha256,
    checksums}``, newest first."""
    query_os, query_arch, file_os, suffix = TARGETS[target]
    url = (f"{MARKETPLACE}/{line}?os={query_os}&architecture={query_arch}"
           f"&image_type=jdk&page_size=100")
    try:
        releases = json.loads(borrow.fetch(url, headers=AGENT))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return []
        raise SystemExit(f"the Microsoft marketplace entry for {line} answered {error.code}") from error

    name = re.compile(
        rf"microsoft-jdk-(\d+(?:\.\d+)*)-{file_os}-{query_arch}\.{re.escape(suffix)}"
    )
    found = []
    for release in releases:
        for binary in release.get("binaries", ()):
            package = binary.get("package") or {}
            match = name.fullmatch(package.get("name", ""))
            if binary.get("image_type") != "jdk" or not match:
                continue
            found.append({
                "version": match.group(1),
                "release": release["release_name"],
                "url": package["link"],
                # `sha256sum`, and never the `sha265sum` beside it: the Marketplace document
                # carries both spellings with one value, and only one of them is a word.
                "sha256": package["sha256sum"].lower(),
                "checksums": package["sha256sum_link"],
            })
    return sorted(found, key=lambda entry: borrow.parts(entry["version"]), reverse=True)


def resolve(spec: str, target: tuple[str, str]) -> dict:
    """Turn ``21``, ``21.0.12.1`` or ``latest`` into one release for this cell.

    A line that is not an LTS line Microsoft builds is a refusal rather than an empty cell: nothing
    upstream is missing for this target, this row does not offer it.
    """
    offered = lines()
    if spec == "latest":
        line, asked = offered[-1], ()
    else:
        asked = borrow.parts(spec)
        line = asked[0]
        if line not in offered:
            raise SystemExit(
                f"MixEngine offers the LTS lines {', '.join(map(str, offered))} of Microsoft Build of "
                f"OpenJDK; {spec!r} is not one of them"
            )

    releases = catalogue(line, target)
    if not releases:
        borrow.unavailable(f"Microsoft lists no JDK {line} for {target[0]}/{target[1]}")

    def padded(version: str) -> tuple[int, ...]:
        parts = borrow.parts(version)
        return parts + (0,) * (len(asked) - len(parts))

    candidates = [entry for entry in releases if padded(entry["version"])[: len(asked)] == asked]
    if not candidates:
        raise SystemExit(
            f"Microsoft lists no JDK {spec}. On {line} it offers "
            f"{', '.join(entry['version'] for entry in releases)}"
        )
    return candidates[0]
