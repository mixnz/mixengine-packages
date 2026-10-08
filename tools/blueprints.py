#!/usr/bin/env python3
"""The gallery this repository signs, and the checks that have to hold before it does.

MixEngine's gallery is compiled into that binary and trusted there without a signature — one
travelling inside the binary that holds the key would prove nothing the binary has not proved
already. What this repository publishes is the *other* channel: the same manifests as files, each
with a detached minisign signature, so a blueprint downloaded by hand lands trusted rather than
untrusted for good. MixEngine's roadmap task T79a.

Three jobs, and deliberately not a fourth:

1. **Read the gallery.** Every file parses as TOML and every *stem* is a slug MixEngine will accept.
   The stem is what is checked because the stem is what a blueprint gets filed under;
   ``[blueprint] name`` is display text and says ``Next.js``.
2. **Prove the key chain.** The public key committed here has to be the constant compiled into the
   MixEngine being published from. A signature made with a key no installed copy accepts is worse
   than no signature: it looks published.
3. **Compare with what is published**, which is what the weekly check does with it — the signed
   manifests, and since mixlab's T205b the starters ``publish-blueprints`` puts beside them.

**Not a second renderer.** Whether a manifest is in canonical form is settled by ``manifest::render``
over there and asserted by MixEngine's own tests. A Python opinion about that would be a second
answer to a question that has to have one.

The roster is read from the directory rather than written down here. How many blueprints the gallery
holds is MixEngine's decision, and a copy of it kept in this repository would be a copy to keep in
step by hand.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

# `blueprints::store::validated_slug`, spelled again because this repository cannot call it. A slug
# is joined onto a directory path over there, which is why it is this narrow.
SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# The constant in `crates/mixengine-core/src/blueprints/trust.rs`.
KEY_IN_SOURCE = re.compile(r'pub const PUBLIC_KEY: &str = "([^"]+)"')


def gallery(directory: Path) -> tuple[list[Path], list[str]]:
    """Every manifest in ``directory``, and everything wrong with them."""
    files = sorted(directory.glob("*.toml"))
    problems: list[str] = []

    if not files:
        return files, [f"{directory} holds no .toml file — is this a mixengine checkout?"]

    for file in files:
        if not SLUG.match(file.stem):
            problems.append(
                f"{file.name}: '{file.stem}' is not a slug MixEngine will file — lower-case "
                "letters, digits and hyphens only, and not at either end"
            )
        try:
            tomllib.loads(file.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
            problems.append(f"{file.name}: does not parse — {error}")

    return files, problems


def key_chain(source: Path, public: Path) -> list[str]:
    """Whether the key committed here is the one MixEngine checks against."""
    compiled = KEY_IN_SOURCE.search(source.read_text(encoding="utf-8"))
    if compiled is None:
        return [f"{source}: no `pub const PUBLIC_KEY` to compare against — did it move?"]

    lines = [line for line in public.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 2:
        return [f"{public}: expected an untrusted comment and one key line, found {len(lines)}"]

    if lines[1].strip() != compiled.group(1):
        return [
            "the key this repository signs with is not the key MixEngine checks against:\n"
            f"    {public}: {lines[1].strip()}\n"
            f"    {source}: {compiled.group(1)}\n"
            "    rotating the gallery key is an application release — the MixEngine carrying the "
            "new key goes out first"
        ]

    return []


def published(files: list[Path], base: str) -> list[str]:
    """Whether every manifest published under ``base`` is still the one on disk."""
    problems: list[str] = []

    for file in files:
        url = f"{base.rstrip('/')}/{file.name}"
        try:
            with urllib.request.urlopen(url, timeout=60) as answer:
                served = answer.read()
        except (urllib.error.URLError, TimeoutError) as error:
            problems.append(f"{file.name}: {url} could not be read — {error}")
            continue

        if served != file.read_bytes():
            problems.append(
                f"{file.name}: what is published is not what the gallery holds — "
                "cut it again with release/publish-blueprints.sh"
            )

    return problems


def tree_entries(folder: Path) -> dict[str, bytes]:
    """Every file under ``folder``, named as ``zip -r <name>`` names it."""
    return {
        f"{folder.name}/{path.relative_to(folder).as_posix()}": path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def zip_entries(data: bytes) -> dict[str, bytes]:
    """Every file in a zip, directories left out.

    **Names and contents, never the zip's own bytes.** ``zip -X`` still records modification times,
    and a checkout sets them to the moment of checkout, so two zips of one tree never match byte for
    byte.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as answer:
        return answer.read()


def starters(directory: Path, base: str, assets: list[str],
             fetch: Callable[[str], bytes]) -> list[str]:
    """Whether every starter published under ``base`` is still the one in ``directory``.

    A folder is published as ``<name>-starter.zip`` and compared entry by entry; a file directly
    under ``starters/`` (``rails-template.rb``) is published as itself and compared byte for byte.
    A starter the release holds and the tree no longer does is a drift too. ``assets`` is the
    release's asset names; ``fetch`` reads one URL, so a test can stand in for the network.
    """
    problems: list[str] = []
    base = base.rstrip("/")
    expected: set[str] = set()
    unreadable = (urllib.error.URLError, TimeoutError, KeyError, zipfile.BadZipFile)

    for path in sorted(directory.iterdir()):
        if path.is_dir():
            name = f"{path.name}-starter.zip"
            expected.add(name)
            try:
                served = zip_entries(fetch(f"{base}/{name}"))
            except unreadable as error:
                problems.append(f"{name}: could not be read — {error}")
                continue
            tree = tree_entries(path)
            differing = next(
                (entry for entry in sorted(set(tree) | set(served))
                 if tree.get(entry) != served.get(entry)),
                None,
            )
            if differing is not None:
                problems.append(
                    f"{name}: {differing} differs from starters/{path.name} — "
                    "cut it again with release/publish-blueprints.sh"
                )
        elif path.is_file():
            expected.add(path.name)
            try:
                served_bytes = fetch(f"{base}/{path.name}")
            except unreadable as error:
                problems.append(f"{path.name}: could not be read — {error}")
                continue
            if served_bytes != path.read_bytes():
                problems.append(
                    f"{path.name}: what is published is not starters/{path.name} — "
                    "cut it again with release/publish-blueprints.sh"
                )

    for asset in assets:
        is_manifest = asset.endswith((".toml", ".minisig"))
        if not is_manifest and asset not in expected:
            problems.append(f"{asset}: published, and starters/ no longer holds it")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--gallery",
        type=Path,
        required=True,
        help="the gallery directory in a mixengine checkout",
    )
    parser.add_argument(
        "--key-source",
        type=Path,
        help="blueprints/trust.rs in the same checkout, to prove the key chain",
    )
    parser.add_argument(
        "--pub",
        dest="public",
        type=Path,
        default=Path("blueprints.pub"),
        help="the public key committed here (default: blueprints.pub)",
    )
    parser.add_argument(
        "--published",
        metavar="URL",
        help="compare the gallery with what is published under this base URL",
    )
    parser.add_argument(
        "--starters",
        type=Path,
        help="blueprints/starters in the same checkout, compared with what is published",
    )
    parser.add_argument(
        "--assets",
        type=Path,
        help="the release's asset names, one per line (gh release view --json assets)",
    )
    asked = parser.parse_args()

    files, problems = gallery(asked.gallery)

    if asked.key_source is not None:
        problems += key_chain(asked.key_source, asked.public)

    # Only when the gallery itself is sound: comparing a directory that could not be read against a
    # release says nothing, and twelve download failures would bury the one line that matters.
    if asked.published and not problems:
        problems += published(files, asked.published)

    if asked.published and asked.starters and not problems:
        assets = asked.assets.read_text().split() if asked.assets else []
        problems += starters(asked.starters, asked.published, assets, download)

    for file in files:
        print(f"  {file.stem:<12} {file.name}")
    print(f"{len(files)} blueprint(s) in {asked.gallery}")

    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
