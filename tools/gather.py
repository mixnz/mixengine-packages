#!/usr/bin/env python3
"""Decide which released versions the index has to look at, and look at only those.

`publish-index.yml` used to download every asset of every release on every run, to describe again
what the published index already described. GitHub states a sha256 and a size for every asset, so
one listing is enough to tell a version the index already has right from one it does not. Only the
second kind is downloaded — one version at a time, checked by `parity.py`, read by
`mkindex.collect`, and deleted before the next — so the disk a run needs is the largest single
version rather than the whole archive.

The digest is only ever a reason to look or not to look. Nothing from the listing is written into
the index: a settled artifact keeps the hash taken from its bytes when it was first indexed, and a
changed one is hashed again from the bytes downloaded.

    python tools/gather.py --previous <index URL> --base-url <releases URL> --out work/found.json
    python tools/gather.py --previous <index URL> --base-url <releases URL> --plan   # decide only

Python 3 stdlib only; needs `gh`, and `GH_REPO` or a checkout for it to know the repository.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mkindex  # noqa: E402  — siblings, and this directory is not importable as a package

TOOLS = Path(__file__).resolve().parent
ARCHIVE_SUFFIXES = (".zip", ".tar.zst", ".tar.gz")


def cells(release: dict) -> dict[str, tuple[str | None, int]]:
    """``{archive name: (sha256 or None, size)}`` for the artifacts of one release.

    An archive without a manifest beside it is not an artifact — `mysql-5.7.44-patched-src.tar.gz`
    is a source tarball kept for the record — and is left out, as `mkindex.collect` leaves it out.
    """
    assets = {asset["name"]: asset for asset in release["assets"]}
    found = {}
    for name, asset in assets.items():
        if name.endswith(ARCHIVE_SUFFIXES) and f"{name}.json" in assets:
            digest = asset.get("digest") or ""
            found[name] = (digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
                           asset["size"])
    return found


def indexed(index: dict) -> dict[str, dict[str, tuple[str, int]]]:
    """``{tag: {archive name: (sha256, size)}}`` — what the published index says is there."""
    found: dict[str, dict[str, tuple[str, int]]] = {}
    for package in index.get("packages", []):
        tag = f"{package['kind']}-{package['version']}"
        for artifact in package["artifacts"]:
            name = artifact["url"].rsplit("/", 1)[1]
            found.setdefault(tag, {})[name] = (artifact["sha256"], artifact["size"])
    return found


def of_kind(tag: str, kind: str) -> bool:
    """Whether *tag* is a version of *kind*: `mongo` must not claim `mongodb-8.0.1`."""
    return tag.startswith(f"{kind}-") and tag[len(kind) + 1:len(kind) + 2].isdigit()


def verdicts(releases: list[dict], index: dict, recheck: str = "") -> tuple[list[str], list[str]]:
    """``(tags to look at, what to say)`` from the listing and the published index alone."""
    known = indexed(index)
    look, said, listed = [], [], set()
    for release in releases:
        tag = release["tag_name"]
        there = cells(release)
        if not there:
            continue
        listed.add(tag)
        was = known.get(tag)
        reasons = []
        if was is None:
            reasons.append("not in the index")
        else:
            for name, (digest, size) in sorted(there.items()):
                if name not in was:
                    reasons.append(f"{name} is a cell the index does not have")
                elif digest is None:
                    reasons.append(f"{name} has no digest to compare")
                elif (digest, size) != was[name]:
                    reasons.append(f"{name} is not the archive the index describes — published "
                                   f"bytes were replaced")
            for name in sorted(set(was) - set(there)):
                said.append(f"::warning::{tag}: the index names {name} and the release no longer "
                            f"has it. The index keeps it; check-archive.yml is what reports it.")
        if not reasons and (recheck == "all" or (recheck and of_kind(tag, recheck))):
            reasons.append("recheck was asked for")
        if reasons:
            look.append(tag)
            said.append(f"{tag}: {'; '.join(reasons)}")

    # A listing that came back empty is an API that did not answer, not an archive that is gone,
    # and republishing on the strength of it would report success for a run that saw nothing.
    if known and not listed:
        raise SystemExit("the release listing names no artifact and the index names "
                         f"{len(known)} version(s); refusing to read that as nothing being new")
    if recheck not in ("", "all") and not any(of_kind(tag, recheck) for tag in listed):
        raise SystemExit(f"recheck: no released version is a '{recheck}'")

    for tag in sorted(set(known) - listed):
        said.append(f"::warning::{tag} is in the index and has no release. The index keeps it; "
                    f"check-archive.yml is what reports it.")
    return sorted(look), said


def listing() -> list[dict]:
    """Every release of this repository with its assets — all of them, however many there are."""
    done = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", "repos/{owner}/{repo}/releases?per_page=100"],
        capture_output=True, text=True, check=True,
    )
    return [release for page in json.loads(done.stdout) for release in page]


def download(tag: str, directory: Path) -> None:
    subprocess.run(["gh", "release", "download", tag, "--dir", str(directory), "--pattern", "*"],
                   check=True)


def parity(directory: Path) -> bool:
    """Whether the cells in *directory* agree. What they disagree about is printed by the check."""
    return subprocess.run([sys.executable, str(TOOLS / "parity.py"), "--artifacts", str(directory),
                           "--quiet"]).returncode == 0


def gather(tags: list[str], base_url: str, work: Path,
           download=download, parity=parity) -> tuple[list, list[str]]:
    """Look at each of *tags* in turn. ``(artifacts found, tags whose cells disagree)``.

    One version on disk at a time, and gone before the next is fetched — including when the check
    fails, because a run that stops at the first disagreement says nothing about the second.
    """
    found, refused = [], []
    for tag in tags:
        directory = work / tag
        directory.mkdir(parents=True, exist_ok=True)
        try:
            download(tag, directory)
            if parity(directory):
                found += mkindex.collect(directory, base_url)
            else:
                refused.append(tag)
        finally:
            shutil.rmtree(directory, ignore_errors=True)
    return found, refused


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", help="path or URL of the published index")
    parser.add_argument("--base-url", required=True, help="where release assets live")
    parser.add_argument("--recheck", default="",
                        help="a kind, or 'all': look at those versions even if nothing changed")
    parser.add_argument("--work", type=Path, default=Path("work"))
    parser.add_argument("--out", type=Path, default=Path("work/found.json"))
    parser.add_argument("--plan", action="store_true", help="decide and say, download nothing")
    args = parser.parse_args()

    look, said = verdicts(listing(), mkindex.load_previous(args.previous), args.recheck.strip())
    for line in said:
        print(line)
    print(f"{len(look)} version(s) to look at")
    if args.plan:
        return

    found, refused = gather(look, args.base_url, args.work)
    if refused:
        raise SystemExit(f"{len(refused)} version(s) whose cells disagree: {', '.join(refused)}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(found)} artifact(s)")


if __name__ == "__main__":
    main()
