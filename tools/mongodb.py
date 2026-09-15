#!/usr/bin/env python3
"""Borrow a MongoDB server build from mongodb.org and repack it as a MixEngine artifact.

**The row that existed as half a promise.** Every PHP this repository publishes carries the
``mongodb`` extension, on every branch and every cell, because ``php_legacy_unix.py`` fails a build
without it — *"MixEngine offers {package} on every version it ships, so an artifact without it is
not one worth publishing"*. Nothing here installed a MongoDB for it to talk to. This is that half.

The floor is **6.0**, and it is upstream's rather than a preference. Two lines below it were
abandoned on macOS while they were still being patched — ``4.4.29`` and ``5.0.31`` publish a
``macos-x86_64`` tarball and ``4.4.31`` and ``5.0.34`` publish no macOS asset at all — and macOS on
Apple Silicon starts at 6.0. Filling those cells would mean compiling MongoDB on macOS for a line
upstream has given up on there, which is the MySQL 5.6/5.7 shape at a higher price.

**Which lines exist is read off upstream's catalogue rather than written down here.** A release is
offered when it is flagged ``production_release`` *and* ``lts_release``; the rapid releases between
the LTS ones carry ``continuous_release``, live a few months, and are not something a blueprint
should be able to pin.

**Windows on ARM is upstream's empty cell.** No MongoDB has ever been built for it, at any version,
so that cell states itself through ``borrow.unavailable`` rather than being written down here and
going stale.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import mongodb_smoke  # noqa: E402
import relocate  # noqa: E402
import strip  # noqa: E402

# The newest release of every line, 400 KB, which is what a `--version 8.3` run needs. `full.json`
# is 50 MB and holds every patch ever published; it is fetched only when an exact older version is
# asked for and `current.json` does not have it.
CURRENT = "https://downloads.mongodb.org/current.json"
FULL = "https://downloads.mongodb.org/full.json"

# (os, arch) -> upstream's `target` spelling, and the archive suffix.
#
# Linux is the one cell whose target is not a constant: upstream builds per distribution and the
# builds differ in which OpenSSL they expect. `linux_download` decides it by measurement.
TARGETS = {
    ("windows", "x86_64"): ("windows", "zip"),
    ("macos", "aarch64"): ("macos", "tgz"),
    ("macos", "x86_64"): ("macos", "tgz"),
    ("linux", "x86_64"): ("linux", "tgz"),
    ("linux", "aarch64"): ("linux", "tgz"),
}

# Upstream's spelling for an architecture, per target. macOS says `arm64` where this repository says
# `aarch64`, and Linux says `aarch64` like everybody else.
ARCH = {
    "macos": {"aarch64": "arm64", "x86_64": "x86_64"},
    "windows": {"x86_64": "x86_64"},
    "linux": {"aarch64": "aarch64", "x86_64": "x86_64"},
}

# **Community MongoDB is not one edition name, and reading it as one finds nothing.** The catalogue
# calls the macOS and Windows community builds `base` and the Linux ones `targeted`, because on
# Linux there is a build per distribution and the word names that rather than the licence. The
# third spelling, `enterprise`, is a different product under a different licence and is never taken
# here — it is excluded by naming what *is* wanted rather than by excluding it, which is the
# difference between a filter that fails closed and one that fails open.
EDITION = {"macos": "base", "windows": "base", "linux": "targeted"}

# **The floor is this repository's decision and the catalogue cannot make it.** The design this
# recipe was written from claimed that `production_release` and `lts_release` together select the
# five lines offered here; measured against `current.json`, they select seven — upstream flags 5.0
# and 4.4 as LTS production releases too, and goes on publishing patches for them. The two flags do
# the half they can do, which is telling an LTS line from the rapid releases between them, and this
# says the rest: below 6.0 a line cannot be offered *whole*, because upstream withdrew macOS from
# both while they were still being patched. `4.4.29` and `5.0.31` publish a `macos-x86_64` tarball;
# `4.4.31` and `5.0.34` publish no macOS asset of any kind. Offering them would mean either
# compiling MongoDB on macOS for a line upstream has abandoned there, or publishing two lines that
# quietly mean less than the five above them.
FLOOR = (6, 0)

# Upstream's Linux builds, lowest glibc floor first. The order is a preference, not a decision:
# which one is taken is settled by `needed` below, because the two things that matter — the glibc
# floor and which OpenSSL the build expects — are properties of the binary rather than of the name.
LINUX_CANDIDATES = ("rhel8", "rhel90", "rhel93", "rhel10", "ubuntu2004", "ubuntu2204", "ubuntu2404")

# What the archive is expected to hold, per OS. Two binaries: the server and the router. There is no
# shell here and there has not been one since 6.0 — `mongosh` is its own kind, published from its
# own repository under its own licence, which is `tools/mongosh.py`.
LAYOUT = {
    "windows": {"mongod": "bin/mongod.exe", "mongos": "bin/mongos.exe"},
    "unix": {"mongod": "bin/mongod", "mongos": "bin/mongos"},
}

# Removed from every cell, and the reason each one goes. `install_compass` and `Install-Compass.ps1`
# are the same file under two names: a script that downloads and installs MongoDB Compass, which is
# a different product and is not what anybody asked this daemon to install.
NOT_SHIPPED = {
    "bin/install_compass": "a downloader for MongoDB Compass, which is a different product",
    "bin/Install-Compass.ps1": "a downloader for MongoDB Compass, which is a different product",
    "bin/vc_redist.x64.exe": (
        "the Visual C++ redistributable installer — 25.4 MB of setup program that no running "
        "process reads. The precondition it exists to satisfy is stated as requires.vcredist "
        "instead, measured off mongod.exe's import table."
    ),
}


def catalogue(exact: bool) -> list[dict]:
    """Upstream's release records, newest first.

    *exact* asks for the full catalogue, which is fifty megabytes and the only place a patch older
    than a line's newest is listed.
    """
    url = FULL if exact else CURRENT
    document = json.loads(borrow.fetch(url))
    return document["versions"]


def offered(records: list[dict]) -> dict[str, dict]:
    """Offered line -> its newest record: an LTS production release at or above `FLOOR`.

    Two conditions rather than one, because they answer different questions. Upstream's flags say
    which lines are LTS at all — that is a fact about upstream's schedule and it would go stale if
    it were written down here. `FLOOR` says which of those can be offered on six cells, which is a
    fact about what upstream *built*, and upstream states it nowhere.
    """
    found: dict[str, dict] = {}
    for record in records:
        if not (record.get("production_release") and record.get("lts_release")):
            continue
        parts = tuple(int(number) for number in record["version"].split(".")[:2])
        if parts < FLOOR:
            continue
        found.setdefault(".".join(str(number) for number in parts), record)
    return found


def needed(path: Path) -> list[str]:
    """The ``DT_NEEDED`` sonames of an ELF file, in the order the file lists them.

    Read here rather than through ``relocate.elf_dependencies``, which shells out to ``ldd`` and
    therefore answers only on Linux. This has to answer on whichever machine is *choosing* the
    build, and a choice that can only be checked on the platform it is made for is a choice nobody
    reviews. ``strip.py`` parses ELF the same way and for the same reason.
    """
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2:
        raise SystemExit(f"{path} is not a 64-bit ELF file")

    (section_offset,) = struct.unpack_from("<Q", data, 0x28)
    entry_size, count, names_index = struct.unpack_from("<HHH", data, 0x3A)

    def section(index: int) -> tuple[int, int, int]:
        base = section_offset + index * entry_size
        name, _kind, _flags, _addr, offset, size = struct.unpack_from("<IIQQQQ", data, base)
        return name, offset, size

    _, names_offset, names_size = section(names_index)
    names = data[names_offset:names_offset + names_size]

    sections = {}
    for index in range(count):
        name, offset, size = section(index)
        spelling = names[name:names.index(b"\0", name)].decode()
        sections[spelling] = (offset, size)

    if ".dynamic" not in sections or ".dynstr" not in sections:
        return []
    dynamic_offset, dynamic_size = sections[".dynamic"]
    strings_offset, strings_size = sections[".dynstr"]
    strings = data[strings_offset:strings_offset + strings_size]

    sonames = []
    for position in range(dynamic_offset, dynamic_offset + dynamic_size, 16):
        tag, value = struct.unpack_from("<Qq", data, position)
        if tag == 0:                       # DT_NULL
            break
        if tag == 1:                       # DT_NEEDED
            sonames.append(strings[value:strings.index(b"\0", value)].decode())
    return sonames


def linux_download(record: dict, arch: str, work: Path) -> tuple[dict, Path, Path]:
    """The Linux build this cell takes, chosen by reading the binaries rather than the names.

    Tries the candidates in order and stops at the first whose ``mongod`` does not name an OpenSSL
    1.1 soname. OpenSSL 1.1.1 has been unpatched since September 2023, and two glibc versions of
    reach are not what this repository trades a TLS library's security support for.

    The loop prints what it rejected, so a green run says why it took what it took.
    """
    attempted = []
    for candidate in LINUX_CANDIDATES:
        download = next(
            (d for d in record["downloads"]
             if d.get("edition") == EDITION["linux"] and d.get("target") == candidate
             and d.get("arch") == arch),
            None,
        )
        if download is None:
            attempted.append(f"{candidate}: upstream built none")
            continue

        url = download["archive"]["url"]
        print(f"trying {url}")
        archive = work / url.rsplit("/", 1)[-1]
        try:
            urllib.request.urlretrieve(url, archive)
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{url} answered {error.code}") from error

        tree = borrow.unpack(archive, work / f"unpacked-{candidate}", "tgz")
        sonames = needed(tree / "bin" / "mongod")
        stale = [name for name in sonames if name.endswith(".so.1.1")]
        if not stale:
            print(f"{candidate}: {', '.join(sonames)}")
            return download, archive, tree
        attempted.append(f"{candidate}: wants {', '.join(stale)}")
        print(f"{candidate} rejected — {', '.join(stale)} is OpenSSL 1.1.1, unpatched since 2023")

    raise SystemExit(
        f"no Linux build of MongoDB {record['version']} for {arch} links OpenSSL 3: "
        + "; ".join(attempted)
    )


def download_for(record: dict, target: tuple[str, str]) -> dict | None:
    """The community download for this cell, or None where upstream built none.

    Linux never comes through here — its target is chosen by `linux_download`, which has several
    candidates to weigh and a binary to read before it can say which. This answers for the two
    platforms upstream builds exactly once.
    """
    _, arch = target
    upstream_target, _suffix = TARGETS[target]
    want = ARCH[upstream_target][arch]
    for download in record["downloads"]:
        if download.get("edition") != EDITION[upstream_target]:
            continue
        if download.get("target") != upstream_target or download.get("arch") != want:
            continue
        return download
    return None


def refuse(spec: str, lines: dict[str, dict]) -> None:
    """End the run saying why this line is not on offer, which is two different sentences."""
    try:
        parts = tuple(int(number) for number in spec.split(".")[:2])
    except ValueError:
        parts = ()

    if parts and parts < FLOOR:
        raise SystemExit(
            f"MongoDB {'.'.join(str(n) for n in parts)} is below this repository's floor of "
            f"{FLOOR[0]}.{FLOOR[1]}. Upstream still patches it and still calls it LTS, and it "
            "cannot be offered whole: macOS was withdrawn from 4.4 and 5.0 while both were alive, "
            "so the newest patch of either has no macOS build at all. See docs/packages/mongodb.md."
        )
    raise SystemExit(
        f"MongoDB {spec} is not a line this repository offers. Offered: "
        f"{', '.join(sorted(lines))}. A line is offered when upstream flags it production_release "
        "and lts_release and it is at or above the floor; adding one is a roadmap entry rather "
        "than an input."
    )


def resolve(spec: str, target: tuple[str, str]) -> tuple[str, dict | None]:
    """Turn ``8.3``, ``8.3.11`` or ``latest`` into one published archive for this cell.

    The download comes back as ``None`` on Linux, where there is not one archive to name: upstream
    builds per distribution and :func:`linux_download` chooses between them by reading binaries it
    has to fetch first. **This is what the first CI run found.** ``download_for`` looked for a
    download whose ``target`` is ``"linux"``, upstream publishes no such thing — the field holds
    ``rhel8`` or ``ubuntu2204`` — so every Linux leg reported an empty cell five seconds in and
    exited 75, which is the answer for a cell upstream never built rather than for one this function
    was looking up wrong.
    """
    if target not in TARGETS:
        borrow.unavailable(
            f"MongoDB has never been built for {target[0]}/{target[1]} — no version of it, "
            "at any line. This cell is upstream's, not this repository's."
        )

    exact = spec.count(".") >= 2
    lines = offered(catalogue(exact=exact))

    if spec == "latest":
        record = lines[max(lines, key=lambda line: tuple(int(n) for n in line.split(".")))]
    elif spec in lines:
        record = lines[spec]
    elif exact:
        line = ".".join(spec.split(".")[:2])
        if line not in lines:
            refuse(line, lines)
        record = next(
            (r for r in catalogue(exact=True)
             if r["version"] == spec and r.get("production_release")),
            None,
        )
        if record is None:
            raise SystemExit(f"upstream lists no production release {spec}")
    else:
        refuse(spec, lines)

    if target[0] == "linux":
        return record["version"], None

    download = download_for(record, target)
    if download is None:
        borrow.unavailable(
            f"upstream published no {target[0]}/{target[1]} build of MongoDB "
            f"{record['version']}; nothing to borrow for this cell."
        )
    return record["version"], download


def subtract(tree: Path) -> list[str]:
    """Delete what a running process does not read, and answer with what was deleted.

    Two kinds of thing. The named ones in `NOT_SHIPPED`, and every ``.pdb`` — upstream's Windows zip
    is 923 MB of which 844 MB is `mongod.pdb` and `mongos.pdb`. ``borrow.undebugged`` does not catch
    those: it reads DWARF sections *inside* binaries, and a `.pdb` is a file of its own, so this is
    the recipe's decision and is declared in ``upstream.removed`` rather than left to be inferred
    from a size.
    """
    removed = []
    for relative in sorted(NOT_SHIPPED):
        path = tree / relative
        if path.exists():
            path.unlink()
            removed.append(relative)

    for path in sorted(tree.rglob("*.pdb")):
        removed.append(path.relative_to(tree).as_posix())
        path.unlink()

    return removed


def vcredist(tree: Path) -> str | None:
    """Which Visual C++ runtime ``mongod.exe`` imports, as the schema spells it.

    Measured off the import table for the reason ``mysql.py`` gives about ``msvcr100.dll``: a line's
    documentation and its binaries disagree, and the binaries are what fails to start. Every toolset
    from 2015 onwards imports the same ``VCRUNTIME140`` family and their redistributables are
    ABI-compatible, so the newest of that family is what is declared — installing it satisfies any
    of them, and naming an older one would be a claim this recipe cannot check.
    """
    binary = tree / LAYOUT["windows"]["mongod"]
    if not binary.exists():
        return None
    imports = sorted({name.lower() for name in relocate.pe_imports(binary)})
    print(f"mongod.exe imports {', '.join(imports)}")
    if any(name.startswith(("vcruntime140", "msvcp140")) for name in imports):
        return "2022"
    return None


def strip_or_keep(tree: Path, binaries: list[Path],
                  operating_system: str) -> tuple[dict[str, str], dict[str, str]]:
    """Strip each binary, or keep the one the platform's own ``strip`` refuses — and say which.

    **Measured on 6.0 and 7.0, where Apple's strip stops rather than finishes:**

        strip -x bin/mongod: fatal error: indirect symbol table entry 10249
        (past the end of the symbol table)

    Both macOS cells of both lines, and no such refusal from 8.0 upwards, so it is something
    upstream changed about how those binaries are linked rather than anything about this pipeline —
    the bytes were checked against the publisher's own SHA-256 two steps earlier.

    Kept rather than refused, which is the trade :func:`strip.symbols` already makes for a file
    whose section and segment tables disagree: *the archive ships either way and upstream's binary
    is the one that works*. What is not optional is saying so. Each kept file goes into ``keeps``
    with the reason, because an artifact 40 MB larger than its siblings for a reason nobody wrote
    down is exactly the saving *One version means one thing* exists to make accountable.

    **`strip` writes in place and a failed one has already written.** So the original is copied
    outside the tree first, put back if the strip stops, and the restored file's digest is compared
    against the one taken before — because "we shipped upstream's bytes" is a claim, and this is
    the only moment anything can check it.
    """
    # Asked once, before anything is caught below. `strip.symbols` raises the same exception type
    # for "this machine has no strip" as for "strip refuses this file", and those want opposite
    # answers: a refusal is upstream's binary and is kept, a missing tool is a runner that cannot
    # produce this artifact at all and must stop rather than quietly ship every symbol table.
    if not shutil.which("strip"):
        raise SystemExit(
            "no `strip` on PATH, and every Unix cell of this kind ships stripped binaries — "
            "packing here would publish a tree no other run of this recipe produces"
        )

    changed: dict[str, str] = {}
    kept: dict[str, str] = {}

    for binary in binaries:
        relative = binary.relative_to(tree).as_posix()
        original = strip.whole(binary)
        spare = tree.parent / f"{binary.name}.before-strip"
        shutil.copy2(binary, spare)
        try:
            changed |= strip.symbols(tree, [binary], strip.IMAGES[operating_system],
                                     operating_system)
        except SystemExit as refusal:
            shutil.copy2(spare, binary)
            if strip.whole(binary) != original:
                raise SystemExit(
                    f"{relative} could not be put back after `strip` stopped part-way through it, "
                    f"so this tree no longer holds what upstream published. Original refusal: "
                    f"{refusal}"
                ) from refusal
            kept[relative] = (
                f"its symbol table, because this platform's `strip` refuses the file rather than "
                f"shrinking it — {refusal}. Upstream's bytes are shipped unchanged; the other "
                f"cells of this version are stripped."
            )
            print(f"keeping {relative} as upstream published it: {refusal}")
        finally:
            spare.unlink(missing_ok=True)

    return changed, kept


def describe(tree: Path, version: str, target: tuple[str, str],
             record: dict, download: dict) -> dict:
    """What is in the archive, as the daemon will read it."""
    operating_system, arch = target
    windows = operating_system == "windows"
    layout = LAYOUT["windows" if windows else "unix"]

    provides = {name: path for name, path in layout.items() if (tree / path).exists()}
    missing = sorted(set(layout) - set(provides))
    if missing:
        raise SystemExit(
            f"the archive provides no {', '.join(missing)} — expected at "
            f"{', '.join(layout[name] for name in missing)}. Contents: "
            f"{sorted(path.name for path in (tree / 'bin').iterdir())[:20]}"
        )

    return {
        "schema": 1,
        "kind": "mongodb",
        "version": version,
        "os": operating_system,
        "arch": arch,
        "source": "borrowed",
        "upstream": {
            "project": "mongodb/mongo",
            # The commit upstream built this release from, which the catalogue publishes and
            # github.com/mongodb/mongo carries as a tag. MongoDB Community Server is SSPL v1, a
            # copyleft in GPLv3's shape, and this is the source route: nothing here is patched, so
            # naming the commit is the whole claim, and a reader can check it without trusting a
            # sentence in a document.
            "release": record.get("public_githash") or record.get("githash", ""),
            "url": download["archive"]["url"],
            "sha256": download["archive"]["sha256"],
            "verified_against": (
                "downloads.mongodb.org's own full.json, over HTTPS to the publisher"
            ),
        },
        "provides": provides,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", required=True,
        help="a line (6.0, 7.0, 8.0, 8.2, 8.3), an exact version (8.3.11), or 'latest'",
    )
    parser.add_argument("--out", default="dist", type=Path)
    args = parser.parse_args()

    target = borrow.host("MongoDB")
    operating_system, arch = target
    windows = operating_system == "windows"
    suffix = TARGETS[target][1] if target in TARGETS else "tgz"

    version, download = resolve(args.version, target)
    if version != args.version:
        print(f"{args.version} resolved to {version}")
    record = next(r for r in catalogue(exact=True) if r["version"] == version)

    work = Path(tempfile.mkdtemp(prefix="mixengine-mongodb-"))
    try:
        if operating_system == "linux":
            download, archive, tree = linux_download(record, ARCH["linux"][arch], work)
        else:
            url = download["archive"]["url"]
            archive = work / url.rsplit("/", 1)[-1]
            print(f"borrowing {url}")
            try:
                urllib.request.urlretrieve(url, archive)
            except urllib.error.HTTPError as error:
                raise SystemExit(f"{url} answered {error.code}") from error
            tree = borrow.unpack(archive, work / "unpacked", suffix)

        published = download["archive"]["sha256"]
        actual = borrow.sha256(archive)
        if actual != published:
            raise SystemExit(f"sha256 mismatch: got {actual}, full.json says {published}")
        print(f"sha256 {actual} (verified against downloads.mongodb.org/full.json)")

        removed = subtract(tree)
        print(f"removed {len(removed)} path(s): {', '.join(removed)}")

        manifest = describe(tree, version, target, record, download)

        # Windows has nothing left to strip once the .pdb files are gone; the Unix cells carry their
        # symbol tables inside the binaries, 45.6 MB of them in mongod alone. Levelling the four
        # down to the one is what makes this version one artifact rather than five.
        changed: dict[str, str] = {}
        kept: dict[str, str] = {}
        if not windows:
            binaries = [tree / path for path in LAYOUT["unix"].values()]
            # `strip.IMAGES` rather than flags chosen here, for the reason `strip.py` opens with:
            # two recipes stripping their own binaries by their own rules would disagree about the
            # same file, and nothing outside either recipe could notice.
            changed, kept = strip_or_keep(tree, binaries, operating_system)
            print(f"stripped {len(changed)} binar{'y' if len(changed) == 1 else 'ies'}"
                  + (f", kept {len(kept)}" if kept else ""))

        manifest = borrow.declare(tree, manifest, removed=removed,
                                  changed=changed or None, keeps=kept or None)

        # The Linux builds name libssl.so.3, libcrypto.so.3 and libcurl.so.4 and expect the machine
        # to have supplied them. Both binaries already carry RUNPATH=$ORIGIN/../lib, so bundling is
        # a copy rather than a rewrite — but `bundle` is what puts the libraries there and `verify`
        # is what says nothing in the tree reaches outside it afterwards.
        if operating_system == "linux":
            bundled = relocate.bundle(tree, libdir="lib")
            print(f"bundled {len(bundled)}: {', '.join(sorted(bundled))}")
            escaping = relocate.verify(tree)
            if escaping:
                raise SystemExit(
                    "after bundling, these still resolve outside the tree: " + "; ".join(escaping)
                )

        # Every cell, every line. MongoDB has refused to start on an x86_64 without AVX since 5.0,
        # and an artifact that cannot state its own precondition hands the user a dead process
        # instead of a sentence.
        requires = {"cpu": "avx"}
        if windows:
            runtime = vcredist(tree)
            if runtime:
                requires["vcredist"] = runtime
        else:
            # Measured off the finished tree, after bundling: the floor of an artifact is the
            # highest floor of anything in it, the libraries it carries included.
            measured = relocate.floor(tree)
            if measured:
                requires[measured[0]] = measured[1]
                print(f"needs {measured[0]} {measured[1]} or newer")
        manifest["requires"] = requires

        # Proven from a directory the tree was moved to, never from where it was produced — which is
        # the difference between an archive that works and an archive that works here.
        elsewhere = borrow.moved(tree)
        try:
            manifest["smoke"] = {
                "relocated": True,
                "ran": mongodb_smoke.server(
                    elsewhere, version, manifest["provides"], operating_system
                ),
            }
        finally:
            borrow.discard(elsewhere)

        borrow.undebugged(tree)
        borrow.publish(tree, manifest, args.out, suffix)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
