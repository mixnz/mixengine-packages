#!/usr/bin/env python3
"""Borrow a Meilisearch Community Edition binary and repack it as a MixEngine artifact.

**The Community Edition, and only it.** Every release publishes two binaries per target, and the
repository is `MIT AND BUSL-1.1`. What separates them was read out of upstream's
`publish-release-assets.yml` rather than inferred: the matrix builds `edition: [community,
enterprise]` and only the enterprise leg passes `--features enterprise`. So `meilisearch-<target>` is
compiled without the Business Source code, and `meilisearch-enterprise-<target>` is never taken.

**One file, and a service.** The payload is a single executable, as Caddy's is, so the whole proof
is running it: indexing a document and finding it again, from a directory it has been moved to.

**The digest is GitHub's, because Meilisearch publishes none.** There is no checksums file among the
assets. The release API reports a `sha256:` digest for every asset, computed by GitHub at upload, and
that is what the download is checked against — weaker than a document the publisher wrote, and
recorded in `upstream.verified_against` as exactly what it is.

**Which cells a release has is read off that release**, the way `caddy.py` does it. `v1.53.2` has no
`meilisearch-macos-amd64` although every earlier release has one and its enterprise twin does, so a
floor written down here would be wrong in one direction or the other.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import eol  # noqa: E402
import relocate  # noqa: E402
import strip  # noqa: E402

API = "https://api.github.com/repos/meilisearch/meilisearch/releases"
RAW = "https://raw.githubusercontent.com/meilisearch/meilisearch"

# (os, arch) -> the Community Edition asset upstream publishes for it. No Windows ARM64: upstream's
# release matrix builds `windows-2022` only, and has never built anything else for Windows.
TARGETS = {
    ("windows", "x86_64"): "meilisearch-windows-amd64.exe",
    ("macos", "aarch64"): "meilisearch-macos-apple-silicon",
    ("macos", "x86_64"): "meilisearch-macos-amd64",
    ("linux", "x86_64"): "meilisearch-linux-amd64",
    ("linux", "aarch64"): "meilisearch-linux-aarch64",
}

MAJOR = 1

LICENCE = "LICENSE-MIT"


def releases() -> list[dict]:
    """Every Meilisearch release on the first two pages, newest first.

    The GitHub API, with a token when the runner has one: unauthenticated requests are limited to
    sixty an hour per address, and runners share addresses.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    found: list[dict] = []
    for page in (1, 2):
        try:
            page_of = json.loads(borrow.fetch(f"{API}?per_page=100&page={page}", headers=headers))
        except urllib.error.HTTPError as error:
            raise SystemExit(f"the Meilisearch release listing answered {error.code}") from error
        found += page_of
        if len(page_of) < 100:
            break
    return found


def resolve(spec: str, target: tuple[str, str]) -> tuple[str, str, str]:
    """Turn ``1``, ``1.53``, ``1.53.2`` or ``latest`` into ``(version, asset url, sha256)``.

    A release that exists and has no asset for this cell is an empty cell (exit 75); a version that
    does not exist is a refusal.
    """
    asset = TARGETS[target]
    asked = () if spec == "latest" else borrow.parts(spec)
    if asked and asked[0] != MAJOR:
        raise SystemExit(f"MixEngine offers Meilisearch {MAJOR}.x; {spec!r} is not one")

    matching: list[tuple[tuple[int, ...], dict]] = []
    for release in releases():
        if release.get("draft") or release.get("prerelease"):
            continue
        match = re.fullmatch(r"v(\d+\.\d+\.\d+)", release.get("tag_name", ""))
        if not match or borrow.parts(match.group(1))[0] != MAJOR:
            continue
        key = borrow.parts(match.group(1))
        if key[: len(asked)] == asked:
            matching.append((key, release))

    if not matching:
        raise SystemExit(f"meilisearch/meilisearch has no stable release matching {spec!r}")

    # The newest release that matches, and only it: falling back to an older patch because the
    # newest one lacks this cell would publish a version whose other cells do not exist.
    version_key, release = max(matching, key=lambda pair: pair[0])
    version = ".".join(map(str, version_key))
    assets = {entry["name"]: entry for entry in release.get("assets", ())}
    if asset not in assets:
        borrow.unavailable(f"Meilisearch v{version} publishes no {asset}")

    digest = assets[asset].get("digest") or ""
    if not digest.startswith("sha256:") or len(digest) != len("sha256:") + 64:
        raise SystemExit(f"v{version}'s {asset} carries no SHA-256 digest in the release API: {digest!r}")
    return version, assets[asset]["browser_download_url"], digest.removeprefix("sha256:")
