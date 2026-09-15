#!/usr/bin/env python3
"""Borrow a mongosh build from mongodb-js/mongosh and repack it as a MixEngine artifact.

**The shell the server stopped carrying.** Through 5.0 a MongoDB archive contained a ``mongo``
shell; from 6.0 it contains none, and ``mongosh`` is published from its own repository, on its own
release clock, under **Apache-2.0** against the server's SSPL v1. So it is a second kind here rather
than a second directory inside the first one: two products under one version number could not answer
whose version it was, which is the whole of *one version means one thing*.

**The Linux asset taken is the one with no OpenSSL suffix.** Upstream publishes three — one per
system OpenSSL, plus one carrying its own. The self-contained one costs about 4 MB against
``-openssl3`` and buys an artifact with nothing to bundle and no opinion about the machine it lands
on, which is the same trade the Python row makes by taking ``python-build-standalone``.

**There is no Windows/aarch64 build**, the same absent cell as the server's, and for the same
reason: upstream has never made one.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import relocate  # noqa: E402

API = "https://api.github.com/repos/mongodb-js/mongosh/releases"

# (os, arch) -> the asset's platform token, and the archive suffix.
TARGETS = {
    ("windows", "x86_64"): ("win32-x64", "zip"),
    ("macos", "aarch64"): ("darwin-arm64", "zip"),
    ("macos", "x86_64"): ("darwin-x64", "zip"),
    ("linux", "x86_64"): ("linux-x64", "tgz"),
    ("linux", "aarch64"): ("linux-arm64", "tgz"),
}

LAYOUT = {"windows": {"mongosh": "bin/mongosh.exe"}, "unix": {"mongosh": "bin/mongosh"}}


def releases() -> list[dict]:
    """Every mongosh release, newest first.

    The GitHub API for the reason the Caddy and Ruby recipes use it — the tags are the catalogue and
    are stated nowhere else — and with the same token handling: unauthenticated requests are limited
    to sixty an hour per IP address, and GitHub's runners share those.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return json.loads(borrow.fetch(f"{API}?per_page=100", headers=headers))


def resolve(spec: str, target: tuple[str, str]) -> tuple[str, str]:
    """Turn ``2``, ``2.11``, ``2.11.1`` or ``latest`` into one published asset URL."""
    if target not in TARGETS:
        borrow.unavailable(
            f"mongosh publishes no {target[0]}/{target[1]} build — the same absent cell as the "
            "MongoDB server's, and for the same reason: upstream has never made one."
        )
    platform, suffix = TARGETS[target]

    published = [release for release in releases()
                 if not release.get("draft") and not release.get("prerelease")]
    if not published:
        raise SystemExit("mongodb-js/mongosh lists no published release")

    if spec == "latest":
        chosen = published[0]
    else:
        wanted = spec.lstrip("v")
        chosen = next(
            (release for release in published
             if release["tag_name"].lstrip("v") == wanted
             or release["tag_name"].lstrip("v").startswith(wanted + ".")),
            None,
        )
        if chosen is None:
            raise SystemExit(f"mongodb-js/mongosh publishes no release {spec}")

    version = chosen["tag_name"].lstrip("v")
    # The plain asset, not the `-openssl3` or `-openssl11` variant beside it.
    name = f"mongosh-{version}-{platform}.{suffix}"
    asset = next((a for a in chosen.get("assets", []) if a["name"] == name), None)
    if asset is None:
        borrow.unavailable(
            f"mongosh {version} publishes no {name}; nothing to borrow for this cell."
        )
    return version, asset["browser_download_url"]


def describe(tree: Path, version: str, target: tuple[str, str], url: str, digest: str) -> dict:
    """What is in the archive, as the daemon will read it."""
    operating_system, arch = target
    layout = LAYOUT["windows" if operating_system == "windows" else "unix"]

    provides = {name: path for name, path in layout.items() if (tree / path).exists()}
    if "mongosh" not in provides:
        raise SystemExit(
            f"the archive provides no mongosh — expected at {layout['mongosh']}. Contents: "
            f"{sorted(path.name for path in tree.iterdir())[:20]}"
        )

    return {
        "schema": 1,
        "kind": "mongosh",
        "version": version,
        "os": operating_system,
        "arch": arch,
        "source": "borrowed",
        "upstream": {
            "project": "mongodb-js/mongosh",
            "release": f"v{version}",
            "url": url,
            "sha256": digest,
            "verified_against": (
                "the digest of the bytes downloaded from the release asset — upstream publishes a "
                "detached .sig per asset and no checksum document"
            ),
        },
        "provides": provides,
    }


def smoke(tree: Path, version: str, provides: dict[str, str]) -> dict:
    """Ask the shell what it is, from a directory it was moved to.

    A shell is packed to be *run*, and unlike a server that is the whole of it: there is nothing to
    configure, health-check or stop. What this proves is the half that actually breaks — a Node
    program that unpacked into a tree it cannot find its own runtime from.
    """
    elsewhere = borrow.moved(tree)
    try:
        binary = elsewhere / provides["mongosh"]
        answer = subprocess.run(
            [str(binary), "--version"], check=True, capture_output=True, text=True, timeout=300,
        ).stdout.strip()
        if version not in answer:
            raise SystemExit(f"mongosh --version answered {answer!r}, expected {version}")
        print(f"smoke: mongosh answered {answer} from {elsewhere}")
        return {"relocated": True, "ran": [f"mongosh --version -> {answer}"]}
    finally:
        borrow.discard(elsewhere)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", required=True,
        help="a line (2 or 2.11), an exact version (2.11.1), or 'latest'",
    )
    parser.add_argument("--out", default="dist", type=Path)
    args = parser.parse_args()

    target = borrow.host("mongosh")
    suffix = TARGETS[target][1] if target in TARGETS else "tgz"
    version, url = resolve(args.version, target)
    if version != args.version:
        print(f"{args.version} resolved to {version}")

    work = Path(tempfile.mkdtemp(prefix="mixengine-mongosh-"))
    try:
        archive = work / url.rsplit("/", 1)[-1]
        print(f"borrowing {url}")
        try:
            urllib.request.urlretrieve(url, archive)
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{url} answered {error.code}") from error

        tree = borrow.unpack(archive, work / "unpacked", suffix)
        manifest = describe(tree, version, target, url, borrow.sha256(archive))
        manifest = borrow.declare(tree, manifest)
        manifest["smoke"] = smoke(tree, version, manifest["provides"])

        if sys.platform != "win32":
            measured = relocate.floor(tree)
            if measured:
                manifest["requires"] = {measured[0]: measured[1]}
                print(f"needs {measured[0]} {measured[1]} or newer")

        borrow.undebugged(tree)
        borrow.publish(tree, manifest, args.out, suffix)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
