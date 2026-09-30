#!/usr/bin/env python3
"""Check an index before it is signed.

A signature says "this is the file we published". It says nothing about whether the file is right,
and once signed a wrong index is a wrong index every client will happily trust. So the checks that
matter run first.

Three of them cannot be expressed in JSON Schema and are the ones most worth having:

1. **No version was lost.** The index is cumulative by promise. Comparing against the published one
   is the only thing that can catch a generator bug that silently drops a package.
2. **Every URL is ours.** An upstream URL passes every structural check and then breaks years later,
   for exactly the old pinned versions the promise was made about.
3. **Every artifact is reachable and hashes to what is claimed** — optional, because it costs a
   download of the whole index, and worth it before a release.

Needs ``jsonschema`` for the structural half; the invariants above run without it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import catalogue  # noqa: E402  — siblings, and this directory is not importable as a package

OURS = "github.com/mixnz/mixengine-packages"


def load(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=60) as response:
            return json.loads(response.read())
    return json.loads(Path(source).read_text(encoding="utf-8"))


def load_published(source: str | None) -> dict | None:
    """The published document a new one is held against, or ``None`` when there is none yet.

    Only "there is none" is ``None``. A server that failed is raised: the workflow used to retry
    without `--previous` whenever this check failed for any reason, which made a first run and a
    lost version the same answer.
    """
    if not source:
        return None
    if source.startswith(("http://", "https://")):
        raw = catalogue.fetch(source)
        return None if raw is None else json.loads(raw)
    path = Path(source)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def structural(index: dict, schema: Path) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        print("jsonschema not installed; skipping the structural half", file=sys.stderr)
        return []
    validator = jsonschema.Draft202012Validator(
        json.loads(schema.read_text(encoding="utf-8"))
    )
    return [
        f"{'/'.join(str(p) for p in error.path)}: {error.message}"
        for error in validator.iter_errors(index)
    ]


def invariants(index: dict, previous: dict | None) -> list[str]:
    problems = []
    seen = set()

    for package in index["packages"]:
        key = (package["kind"], package["version"])
        if key in seen:
            problems.append(f"{key[0]} {key[1]} appears twice")
        seen.add(key)

        platforms = set()
        for artifact in package["artifacts"]:
            where = (artifact["os"], artifact["arch"])
            if where in platforms:
                problems.append(f"{key[0]} {key[1]} has two {where[0]}/{where[1]} artifacts")
            platforms.add(where)

            if OURS not in artifact["url"]:
                problems.append(
                    f"{key[0]} {key[1]} {where[0]}/{where[1]} points outside our mirror: "
                    f"{artifact['url']}"
                )
            if "php" in package["kind"] and artifact["os"] != "windows":
                if "php-fpm" not in artifact["provides"]:
                    problems.append(
                        f"php {key[1]} {where[0]} provides no php-fpm; a site could not be served"
                    )
            # A service is named in a generated `ServiceSpec` by the command the recipe expects, so
            # an artifact whose `provides` is missing it fails at supervision time rather than at
            # install time. Stated per kind, as php-fpm is, because what a service must offer is a
            # fact about that service.
            if package["kind"] == "caddy" and "caddy" not in artifact["provides"]:
                problems.append(
                    f"caddy {key[1]} {where[0]}/{where[1]} provides no caddy; nothing could run it"
                )
            # Two rather than one, and the second is the half a server-only check would miss: a
            # PostgreSQL that cannot be started is useless, and a PostgreSQL that starts with no
            # `initdb` beside it has nothing to start *against* — the data directory is a first-run
            # job rather than part of the install, which is the one thing both databases here agree
            # on and neither says in its file layout.
            # MySQL is the third row and asks for two rather than three, which is upstream's doing:
            # `mysql_install_db` exists in 5.6 and was deleted in 5.7, where `mysqld
            # --initialize-insecure` bootstraps a data directory instead. A required list naming the
            # installer would fail four lines of five for having been written from the oldest.
            for kind, needs in (("mariadb", ("mariadbd", "mariadb-install-db")),
                                ("mysql", ("mysqld", "mysql")),
                                ("postgres", ("postgres", "initdb"))):
                if package["kind"] != kind:
                    continue
                for command in needs:
                    if command not in artifact["provides"]:
                        problems.append(
                            f"{kind} {key[1]} {where[0]}/{where[1]} provides no {command}; the "
                            f"daemon could not supervise it"
                        )

    if previous:
        lost = {(p["kind"], p["version"]) for p in previous["packages"]} - seen
        for kind, version in sorted(lost):
            problems.append(f"{kind} {version} was in the published index and is not in this one")

    return problems


def catalogue_problems(index: dict, files: dict[str, bytes],
                       previous_root: dict | None) -> list[str]:
    """Hold a schema 2 set to the schema 1 index it was encoded from.

    One comparison carries every invariant above across: if decoding the set gives back exactly
    the packages `invariants` just passed, there is nothing schema 2 says that schema 1 does not.
    """
    broken = catalogue.problems(files)
    if broken:
        return broken
    try:
        decoded = catalogue.decode(files)
    except SystemExit as refusal:
        return [str(refusal)]

    problems = []
    root = json.loads(files[catalogue.ROOT])
    if root["generated_at"] != index["generated_at"]:
        problems.append(f"the root's generated_at is {root['generated_at']} and index.json's is "
                        f"{index['generated_at']}")

    if decoded != index["packages"]:
        theirs = {(p["kind"], p["version"]): p for p in decoded}
        ours = {(p["kind"], p["version"]): p for p in index["packages"]}
        for key in sorted(ours):
            if theirs.get(key) != ours[key]:
                problems.append(f"{key[0]} {key[1]} is in index.json and reads differently, or "
                                f"not at all, in schema 2")
        for key in sorted(set(theirs) - set(ours)):
            problems.append(f"{key[0]} {key[1]} is in schema 2 and not in index.json")
        if not problems:
            problems.append("schema 2 lists the same packages in a different order")

    for kind in sorted(set((previous_root or {}).get("kinds", {})) - set(root["kinds"])):
        problems.append(f"{kind} was in the published root and is not in this one")
    return problems


def structural_v2(files: dict[str, bytes], schemas: Path) -> list[str]:
    """Each document of the set against its JSON Schema, named by file."""
    problems = []
    for name, raw in sorted(files.items()):
        schema = schemas / ("index-v2.schema.json" if name == catalogue.ROOT
                            else "index-v2-kind.schema.json")
        problems += [f"{name}: {problem}" for problem in structural(json.loads(raw), schema)]
    return problems


def reachable(index: dict) -> list[str]:
    problems = []
    for package in index["packages"]:
        for artifact in package["artifacts"]:
            try:
                with urllib.request.urlopen(artifact["url"], timeout=300) as response:
                    digest = hashlib.sha256()
                    for block in iter(lambda: response.read(1 << 20), b""):
                        digest.update(block)
            except Exception as error:  # noqa: BLE001 — any failure is the same failure here
                problems.append(f"{artifact['url']}: {error}")
                continue
            if digest.hexdigest() != artifact["sha256"]:
                problems.append(
                    f"{artifact['url']}: hashes to {digest.hexdigest()}, index says "
                    f"{artifact['sha256']}"
                )
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", help="path or URL of the index to check")
    parser.add_argument("--previous", help="the published index it must not have lost anything from")
    parser.add_argument("--schema", type=Path, default=Path("schema/index.schema.json"))
    parser.add_argument("--catalogue", type=Path,
                        help="directory holding the schema 2 set encoded from this index")
    parser.add_argument("--previous-root",
                        help="the published schema 2 root, which may not have lost a kind")
    parser.add_argument("--fetch", action="store_true",
                        help="download every artifact and check its hash")
    args = parser.parse_args()

    index = load(args.index)
    previous = load_published(args.previous)
    if args.previous and previous is None:
        print(f"nothing is published at {args.previous}; there is nothing to have lost")

    problems = structural(index, args.schema) + invariants(index, previous)
    if args.catalogue:
        files = catalogue.read(args.catalogue)
        problems += catalogue_problems(index, files, load_published(args.previous_root))
        problems += structural_v2(files, args.schema.parent)
    if args.fetch:
        problems += reachable(index)

    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        raise SystemExit(f"{len(problems)} problem(s)")

    artifacts = sum(len(p["artifacts"]) for p in index["packages"])
    said = f"ok: {len(index['packages'])} package(s), {artifacts} artifact(s)"
    if args.catalogue:
        said += f", and a schema 2 set of {len(files) - 1} kind(s) that says the same"
    print(said)


if __name__ == "__main__":
    main()
