#!/usr/bin/env python3
"""Borrow Composer from composer/composer and repack it as a MixEngine artifact.

**One file, six cells.** ``composer.phar`` is PHP bytecode with no operating system in it, and
MixEngine's index has no cell for "any" — so the same payload is packed once per target, in the
archive format that target takes, and the index carries six entries whose only difference is the
wrapper. The day a second OS-independent artifact appears is the day the schema earns a cell; until
then six small uploads cost less than a schema bump every client has to learn.

**Checked against a second publisher, not a keyserver.** Every release carries a PGP ``.asc``, and
verifying it means fetching Composer's release key from a keyserver — a moving dependency on a
machine with nothing installed, the same trade the Node.js and Caddy recipes refuse. What is checked
instead is ``https://getcomposer.org/download/<version>/composer.phar.sha256sum``: the project's own
site, over HTTPS, stating the hash of the file GitHub serves. Two publishers, one hash.

**Proved to run, under the runner's PHP.** A phar has nothing to start on its own, so the proof is
``php composer.phar --version`` from a directory the file was moved to, answering the version being
packed. The workflow pins a PHP with ``setup-php`` so the answer does not depend on which image was
updated last; by hand, any ``php`` on the PATH will do.

Python 3 stdlib only, by policy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package

API = "https://api.github.com/repos/composer/composer/releases"
SECOND_PUBLISHER = "https://getcomposer.org/download/{version}/composer.phar.sha256sum"

# Composer 1 is a different dependency resolver with a different lock format; MixEngine's gallery
# and every current framework want 2.
MAJOR = 2


def releases() -> list[dict]:
    """Every Composer release, newest page first.

    The GitHub API, with the token handling ``caddy.py`` records: unauthenticated requests are
    limited to sixty an hour per IP address, and GitHub's runners share those.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    found: list[dict] = []
    for page in (1, 2, 3):
        request = urllib.request.Request(f"{API}?per_page=100&page={page}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                page_of = json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code in (403, 429) and not token:
                raise SystemExit(
                    "github.com rate-limited the release listing and no GITHUB_TOKEN was set"
                ) from error
            raise SystemExit(f"the Composer release listing answered {error.code}") from error
        found += page_of
        if len(page_of) < 100:
            break
    return found


def resolve(spec: str) -> tuple[str, str]:
    """Turn ``2``, ``2.2``, ``2.10.3`` or ``latest`` into ``(version, composer.phar url)``.

    Tags are bare ``2.10.3``; drafts, pre-releases and anything not ``x.y.z`` are skipped. A line
    is answered with its newest release, which for ``2.2`` is the LTS a PHP older than 7.2.5 needs.
    """
    offered: dict[tuple[int, ...], tuple[str, str]] = {}
    lines: set[str] = set()

    for release in releases():
        if release.get("draft") or release.get("prerelease"):
            continue
        match = re.fullmatch(r"(\d+\.\d+\.\d+)", release.get("tag_name", ""))
        if not match:
            continue
        version = match.group(1)
        if borrow.parts(version)[0] != MAJOR:
            continue
        assets = {asset["name"]: asset["browser_download_url"] for asset in release.get("assets", ())}
        if "composer.phar" not in assets:
            continue
        lines.add(".".join(version.split(".")[:2]))
        offered[borrow.parts(version)] = (version, assets["composer.phar"])

    if not offered:
        borrow.unavailable(f"composer/composer publishes no composer.phar in any {MAJOR}.x release")

    if spec == "latest":
        candidates = sorted(offered)
    else:
        prefix = borrow.parts(spec)
        if prefix[0] != MAJOR:
            raise SystemExit(f"MixEngine offers Composer {MAJOR}.x only")
        candidates = sorted(key for key in offered if key[: len(prefix)] == prefix)

    if not candidates:
        borrow.unavailable(
            f"composer/composer has no {spec}. It offers "
            f"{', '.join(sorted(lines, key=borrow.parts))}."
        )
    return offered[candidates[-1]]


def published_hash(version: str) -> str:
    """The SHA-256 getcomposer.org states for this version's phar."""
    listing = borrow.fetch(SECOND_PUBLISHER.format(version=version)).decode("utf-8", "replace")
    digest, _, filename = listing.strip().partition(" ")
    if filename.strip() != "composer.phar" or len(digest) != 64:
        raise SystemExit(f"getcomposer.org's sha256sum for {version} is not one: {listing!r}")
    return digest


def describe(tree: Path, version: str, target: tuple[str, str], url: str, digest: str) -> dict:
    """What is in the archive, as the daemon will read it."""
    operating_system, arch = target
    if not (tree / "composer.phar").is_file():
        raise SystemExit("the tree holds no composer.phar")

    return {
        "schema": 1,
        "kind": "composer",
        "version": version,
        "os": operating_system,
        "arch": arch,
        "source": "borrowed",
        "upstream": {
            "project": "composer/composer",
            "release": version,
            "url": url,
            "sha256": digest,
            "verified_against": "getcomposer.org composer.phar.sha256sum over HTTPS",
        },
        "provides": {"composer": "composer.phar"},
    }


def smoke(tree: Path, version: str) -> dict:
    """``php composer.phar --version`` from a directory the file was moved to."""
    php = shutil.which("php")
    if php is None:
        raise SystemExit("no php on the PATH: a phar is proved by the PHP that runs it")

    elsewhere = borrow.moved(tree)
    try:
        ran = subprocess.run(
            [php, str(elsewhere / "composer.phar"), "--version", "--no-ansi"],
            capture_output=True, text=True, timeout=120, check=False,
            env={**os.environ, "COMPOSER_HOME": str(elsewhere / ".composer-home")},
        )
    finally:
        borrow.discard(elsewhere)

    if ran.returncode != 0 or f"Composer version {version}" not in ran.stdout:
        raise SystemExit(
            f"php composer.phar --version answered {ran.returncode}: "
            f"{ran.stdout.strip()!r} {ran.stderr.strip()!r}"
        )
    answered = ran.stdout.strip().splitlines()[0]
    print(f"smoke: {answered} (with {php})")

    # `relocated` is what `mkindex.py` reads: nothing goes in the index that was not run from a
    # directory it had been moved to, and for a phar "run" means run by a PHP.
    return {
        "relocated": True,
        "ran": ["php composer.phar --version --no-ansi"],
        "php": php,
        "answered": answered,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", required=True,
        help="exact version (2.10.3), a line (2 or 2.2) for its newest release, or 'latest'",
    )
    parser.add_argument("--out", default="dist", type=Path)
    args = parser.parse_args()

    target = borrow.host("Composer")
    suffix = "zip" if target[0] == "windows" else "tar.zst"

    version, url = resolve(args.version)
    if version != args.version:
        print(f"{args.version} resolved to {version}")

    expected = published_hash(version)

    work = Path(tempfile.mkdtemp(prefix="mixengine-composer-"))
    tree = work / "tree"
    tree.mkdir()
    phar = tree / "composer.phar"
    print(f"borrowing {url}")
    # `borrow.fetch` rather than `urlretrieve`: it retries a connection that timed out, which a
    # release CDN does from time to time, and a phar is small enough to hold in memory.
    phar.write_bytes(borrow.fetch(url, timeout=300))

    actual = borrow.sha256(phar)
    if actual != expected:
        raise SystemExit(f"sha256 mismatch: got {actual}, getcomposer.org says {expected}")
    print(f"sha256 {actual} (verified against getcomposer.org)")

    manifest = describe(tree, version, target, url, actual)
    manifest["smoke"] = smoke(tree, version)

    borrow.publish(tree, manifest, args.out, suffix)
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
