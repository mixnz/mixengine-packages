#!/usr/bin/env python3
"""Refuse to publish over an asset that is already published, before anything is uploaded.

Every build workflow files each artifact under the version its manifest states, and every leg
resolves a line on its own. When two publishers disagree for an hour, a leg builds the older
version and its artifact is uploaded over the published one — same URL, same name, different
bytes, under an index that signed the old ones. That happened to `php-8.2.33` on 2026-09-29; see
docs/the-archive.md. Checking here, at the one place every workflow uploads through, covers that
and every other route to the same result: a re-run by hand, a resolver bug nobody has found yet.

Run between download-artifact and the upload loop:

    python3 tools/no_clobber.py incoming            # fail if anything would be replaced
    python3 tools/no_clobber.py incoming --replace  # a person decided to replace; say what

Nothing is uploaded when it refuses, so a refused run leaves every release exactly as it was.

Python 3 stdlib only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def planned(incoming: Path) -> dict[str, list[str]]:
    """``{tag: [asset names]}`` the upload loop is about to publish — archive and manifest both."""
    found: dict[str, list[str]] = {}
    for manifest in sorted(incoming.glob("*.json")):
        stated = json.loads(manifest.read_text(encoding="utf-8"))
        tag = f"{stated['kind']}-{stated['version']}"
        found.setdefault(tag, []).extend([manifest.name[: -len(".json")], manifest.name])
    return found


def published(tag: str) -> set[str]:
    """The asset names *tag*'s release already has; empty when there is no such release."""
    result = subprocess.run(
        ["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[].name"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.splitlines() if line}


def conflicts(plan: dict[str, list[str]], existing=published) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for tag, names in plan.items():
        taken = existing(tag)
        clash = [name for name in names if name in taken]
        if clash:
            found[tag] = clash
    return found


def main(argv: list[str] | None = None, existing=published) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incoming", type=Path)
    parser.add_argument("--replace", action="store_true",
                        help="a person chose to replace published assets")
    args = parser.parse_args(argv)

    clash = conflicts(planned(args.incoming), existing)
    for tag, names in clash.items():
        level = "warning" if args.replace else "error"
        print(f"::{level}::{tag} already has {', '.join(names)}")
    if clash and not args.replace:
        print("Nothing was uploaded. A leg that built a version already published is either a line "
              "resolved differently on different runners — dispatch the exact version instead — or "
              "a re-run of a published version. Replacing published bytes breaks every hash pinned "
              "against them (docs/the-archive.md); if that is really wanted, dispatch again with "
              "replace on.")
        return 1
    if clash:
        print("replace is on: the assets above will be uploaded over, and the index must be "
              "published again afterwards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
