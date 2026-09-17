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

# Where the JDK proper is, inside what the archive unpacks to. A macOS JDK is a bundle, and the tree
# a daemon reads — `bin`, `lib`, `release` — is its `Contents/Home`. Nothing is moved out of it:
# *repack, do not rearrange*, and `provides` absorbs the difference.
MACOS_HOME = "Contents/Home"

# Removed, relative to the home, where present. Each is read by something that is not in the archive:
# `lib/src.zip` by an IDE, `include` by a C compiler building JNI code, `man` by `man`.
REMOVED = ("lib/src.zip", "include", "man")

COMMANDS = ("java", "javac", "jar", "jshell", "keytool", "jlink")


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


def home(tree: Path, operating_system: str) -> str:
    """The JDK home relative to *tree*, as a POSIX prefix: ``""`` or ``"Contents/Home/"``."""
    if operating_system != "macos":
        return ""
    if not (tree / MACOS_HOME / "release").is_file():
        raise SystemExit(f"a macOS JDK was expected to have its home at {MACOS_HOME}; it does not")
    return f"{MACOS_HOME}/"


def prune(tree: Path, operating_system: str) -> list[str]:
    """Remove what no process in the JDK reads, and answer with what went, as POSIX paths.

    **A delete-list, and a short one**, because almost all of a JDK is read by the JVM: `lib/modules`
    on every start, the CDS archives when the VM maps them, `jmods/` when `jlink` runs. What is left
    is a handful of names that mean the same thing on every line, plus every `.lib` under `lib/` —
    `jvm.lib` and `jawt.lib` on every Windows cell measured, named by suffix so a third is caught.
    """
    prefix = home(tree, operating_system)
    doomed = [tree / f"{prefix}{name}" for name in REMOVED]
    doomed += sorted((tree / f"{prefix}lib").glob("*.lib"))

    removed: list[str] = []
    freed = 0
    for path in doomed:
        if not path.exists():
            continue
        if path.is_dir():
            freed += sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
            shutil.rmtree(path)
        else:
            freed += path.stat().st_size
            path.unlink()
        removed.append(path.relative_to(tree).as_posix())

    print(f"dropped {', '.join(removed) or 'nothing'} ({freed:,} bytes)")
    return removed


def vcredist(tree: Path) -> str | None:
    """The Visual C++ redistributable a Windows JDK needs, which is expected to be none.

    **Not `mongodb.vcredist`, because the question is not the same.** That one reads the import table
    and declares a runtime whenever one is imported. Every Microsoft JDK imports `vcruntime140.dll`
    and `msvcp140.dll` — and ships both, beside `jvm.dll` in `bin/`, with `ucrtbase.dll` on 21 and
    25. A runtime the archive carries is not a precondition of the machine, so what is declared is
    the set that is imported **and absent from the tree**.
    """
    binaries = relocate.machine_files(tree, directories=("bin",))
    shipped = {path.name.lower() for path in binaries}
    imported = {name.lower() for path in binaries for name in relocate.pe_imports(path)}
    runtime = sorted(name for name in imported if name.startswith(("vcruntime140", "msvcp140")))
    missing = [name for name in runtime if name not in shipped]
    print(f"imports {', '.join(runtime) or 'no VC++ runtime'}; "
          f"{'missing ' + ', '.join(missing) if missing else 'all of it shipped in bin/'}")
    return "2022" if missing else None


def describe(
    tree: Path, entry: dict, target: tuple[str, str], removed: list[str], changed: dict[str, str],
) -> dict:
    """What is in the archive, as the daemon will read it."""
    operating_system, arch = target
    prefix = home(tree, operating_system)
    suffix = ".exe" if operating_system == "windows" else ""
    provides = {name: f"{prefix}bin/{name}{suffix}" for name in COMMANDS}
    missing = [name for name, path in provides.items() if not (tree / path).exists()]
    if missing:
        raise SystemExit(f"the archive provides no {', '.join(missing)} under {prefix or '.'}bin/")

    manifest = {
        "schema": 1,
        "kind": "java",
        "version": entry["version"],
        "os": operating_system,
        "arch": arch,
        "source": "borrowed",
        "upstream": {
            "url": entry["url"],
            "sha256": entry["sha256"],
            "verified_against": "the Adoptium Marketplace entry Microsoft publishes, and Microsoft's "
                                ".sha256sum.txt beside the archive, both over HTTPS",
            "project": "microsoft/openjdk",
            "release": entry["release"],
        },
        "provides": provides,
    }
    return borrow.declare(tree, manifest, removed=removed, changed=changed)
