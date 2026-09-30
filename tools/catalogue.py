#!/usr/bin/env python3
"""Schema 2 of the index: one signed root and one file per kind, as an encoding of schema 1.

Nothing here knows a fact schema 1 does not. `encode` takes the index `mkindex.py` builds and
writes it as a root plus a file per kind; `decode` turns that back into the same package list,
value for value, and `verify.py` holds the two to each other before anything is signed. See
docs/superpowers/specs/2026-09-30-index-schema-2-design.md for why it is shaped this way.

    python tools/catalogue.py --decode dist/index-v2-php.json      # the schema 1 view, for a person
    python tools/catalogue.py --changed dist --against <root URL>  # which kind files to upload

Python 3 stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA = 2
ROOT = "index-v2.json"
BASE_URL = "https://github.com/mixnz/mixengine-packages/releases/download"
FORMATS = ("zip", "tar.zst", "tar.gz")

# What an artifact says about its bytes. Everything else it says is its shape, so a field added to
# schema 1 tomorrow lands in the shape without this file hearing about it.
BYTES = ("os", "arch", "url", "sha256", "size")


def kind_file(kind: str) -> str:
    return f"index-v2-{kind}.json"


def compact(document: dict) -> bytes:
    """The one spelling of a document: sorted keys, no whitespace, one trailing newline.

    A kind file is named by its hash, so two runs over the same packages have to produce the same
    bytes or every client downloads seventeen files that did not change.
    """
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def archive_url(base_url: str, kind: str, version: str, os: str, arch: str, fmt: str) -> str:
    stem = f"{kind}-{version}"
    return f"{base_url.rstrip('/')}/{stem}/{stem}-{os}-{arch}.{fmt}"


def encode_kind(kind: str, packages: list[dict], base_url: str) -> dict:
    shapes: list[dict] = []
    seen: dict[str, int] = {}
    encoded = []
    for package in packages:
        artifacts = []
        for artifact in package["artifacts"]:
            fmt = next((f for f in FORMATS if artifact["url"].endswith(f".{f}")), None)
            composed = fmt and archive_url(base_url, kind, package["version"],
                                           artifact["os"], artifact["arch"], fmt)
            if artifact["url"] != composed:
                raise SystemExit(
                    f"{kind} {package['version']} {artifact['os']}/{artifact['arch']} is at "
                    f"{artifact['url']}, which is not where schema 2 would look for it "
                    f"({composed or 'no known archive format'})"
                )
            shape = {name: value for name, value in artifact.items() if name not in BYTES}
            key = json.dumps(shape, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                seen[key] = len(shapes)
                shapes.append(shape)
            artifacts.append({"os": artifact["os"], "arch": artifact["arch"], "format": fmt,
                              "sha256": artifact["sha256"], "size": artifact["size"],
                              "shape": seen[key]})
        entry = {name: value for name, value in package.items() if name not in ("kind", "artifacts")}
        entry["artifacts"] = artifacts
        encoded.append(entry)
    return {"schema": SCHEMA, "kind": kind, "shapes": shapes, "packages": encoded}


def encode(index: dict, base_url: str) -> dict[str, bytes]:
    """``{asset name: bytes}`` — the root and one file per kind — for a schema 1 *index*."""
    kinds: dict[str, list[dict]] = {}
    for package in index["packages"]:
        kinds.setdefault(package["kind"], []).append(package)

    files, entries = {}, {}
    for kind in sorted(kinds):
        raw = compact(encode_kind(kind, kinds[kind], base_url))
        files[kind_file(kind)] = raw
        entries[kind] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    files[ROOT] = compact({"schema": SCHEMA, "generated_at": index["generated_at"],
                           "base_url": base_url.rstrip("/"), "kinds": entries})
    return files


def decode_kind(document: dict, base_url: str) -> list[dict]:
    """The schema 1 packages one kind file stands for."""
    kind, shapes = document["kind"], document["shapes"]
    packages = []
    for package in document["packages"]:
        artifacts = []
        for artifact in package["artifacts"]:
            at = artifact["shape"]
            if not isinstance(at, int) or not 0 <= at < len(shapes):
                raise SystemExit(
                    f"{kind} {package['version']} {artifact['os']}/{artifact['arch']} names shape "
                    f"{at!r} and the file has {len(shapes)}"
                )
            artifacts.append({
                "os": artifact["os"], "arch": artifact["arch"],
                "url": archive_url(base_url, kind, package["version"],
                                   artifact["os"], artifact["arch"], artifact["format"]),
                "sha256": artifact["sha256"], "size": artifact["size"],
                **shapes[at],
            })
        entry = {"kind": kind}
        entry.update({name: value for name, value in package.items() if name != "artifacts"})
        entry["artifacts"] = artifacts
        packages.append(entry)
    return packages


def problems(files: dict[str, bytes]) -> list[str]:
    """What is wrong with a schema 2 set as a set: the root against the bytes it names."""
    if ROOT not in files:
        return [f"there is no {ROOT}"]
    root = json.loads(files[ROOT])
    found = []
    for kind, entry in sorted(root["kinds"].items()):
        raw = files.get(kind_file(kind))
        if raw is None:
            found.append(f"the root names {kind} and there is no {kind_file(kind)}")
            continue
        if len(raw) != entry["size"]:
            found.append(f"{kind_file(kind)} is {len(raw)} bytes and the root says {entry['size']}")
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            found.append(f"{kind_file(kind)} does not hash to what the root says")
    named = {kind_file(kind) for kind in root["kinds"]}
    for name in sorted(files):
        if name != ROOT and name not in named:
            found.append(f"{name} is not named by the root")
    return found


def decode(files: dict[str, bytes]) -> list[dict]:
    """Every schema 1 package a schema 2 set stands for, in the order `mkindex.py` writes them."""
    root = json.loads(files[ROOT])
    packages = []
    for kind in sorted(root["kinds"]):
        packages += decode_kind(json.loads(files[kind_file(kind)]), root["base_url"])
    return packages


def read(directory: Path) -> dict[str, bytes]:
    """The schema 2 set in *directory*: the root and whatever kind files are beside it."""
    return {path.name: path.read_bytes() for path in sorted(directory.glob("index-v2*.json"))}


def fetch(source: str) -> bytes | None:
    """The bytes at *source*, or ``None`` when nothing is published there yet.

    A missing document is the first run and not an error. Anything else is raised, because reading
    "could not be reached" as "does not exist" is how a check stops checking.
    """
    try:
        with urllib.request.urlopen(source, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def changed(files: dict[str, bytes], published: dict | None) -> list[str]:
    """The kind files whose bytes the *published* root does not already name."""
    known = (published or {}).get("kinds", {})
    root = json.loads(files[ROOT])
    return [kind_file(kind) for kind, entry in sorted(root["kinds"].items())
            if known.get(kind, {}).get("sha256") != entry["sha256"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decode", type=Path, metavar="KIND_FILE",
                        help="print the schema 1 view of one kind file")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--changed", type=Path, metavar="DIR",
                        help="print the kind files in DIR that differ from the published root")
    parser.add_argument("--against", help="URL of the published root, for --changed")
    args = parser.parse_args()

    if args.decode:
        document = json.loads(args.decode.read_text(encoding="utf-8"))
        json.dump(decode_kind(document, args.base_url), sys.stdout, indent=2)
        print()
    elif args.changed:
        raw = fetch(args.against) if args.against else None
        print("\n".join(changed(read(args.changed), json.loads(raw) if raw else None)))
    else:
        parser.error("one of --decode or --changed")


if __name__ == "__main__":
    main()
