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
linker reads, and the `man/` pages the Unix cells of 11, 17 and 21 carry. `jmods/` stays, because `jlink`
reads it and `jlink` is in the archive.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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

# What the smoke test compiles. Only APIs from 11, the oldest line: `Runtime.version()` is 9 and
# `HexFormat` would be 17, so the hex is spelled out.
PROGRAM = """import java.security.MessageDigest;

public class Hello {
    public static void main(String[] args) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest("mixengine".getBytes("UTF-8"));
        StringBuilder hex = new StringBuilder();
        for (byte b : digest) {
            hex.append(String.format("%02x", b));
        }
        System.out.println(System.getProperty("java.home"));
        System.out.println(Runtime.version().version());
        System.out.println(hex);
    }
}
"""

# Environment the runner image sets for its own JDK, removed before anything runs: a moved JDK that
# only works because `JAVA_HOME` points at the runner's is not a JDK anybody else can use.
FOREIGN = ("JAVA", "JDK_", "_JAVA", "CLASSPATH")


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


def directories(operating_system: str) -> tuple[str, ...]:
    """Where the machine code of this cell is, for `relocate.verify` and `relocate.floor`."""
    if operating_system == "macos":
        return (f"{MACOS_HOME}/bin", f"{MACOS_HOME}/lib", "Contents/MacOS")
    return ("bin", "lib")


# **What a Linux JDK expects the machine to have**, which Microsoft links dynamically and does not
# ship — measured on the first CI run of 25.0.4.1 and 11.0.32.1, identical on x86_64 and aarch64.
# `libz` is imported by every launcher and by `libjli`, so no JVM starts without it; `freetype` and
# what it pulls in are `libfontmanager`'s, loaded when text is rendered, headless or not; the X11
# family is AWT's and the splash screen's; `libasound` is `javax.sound`'s. This is how every Linux
# JDK is built, Temurin's included, and it is declared rather than bundled — see `requires.libraries`
# in the index schema. The set names what the runner's loader resolved, transitive libraries
# included, so it is what `verify` sets aside; what is *declared* is only what the JDK's own files
# name, measured by `system_libraries`.
LINUX_SYSTEM_LIBRARIES = frozenset({
    "libz.so.1",
    "libfreetype.so.6", "libpng16.so.16", "libbz2.so.1.0", "libbrotlidec.so.1", "libbrotlicommon.so.1",
    "libX11.so.6", "libXext.so.6", "libXi.so.6", "libXrender.so.1", "libXtst.so.6",
    "libxcb.so.1", "libXau.so.6", "libXdmcp.so.6", "libbsd.so.0", "libmd.so.0",
    "libasound.so.2",
})

# The VM itself, relative to the home, per OS.
JVM = {
    "windows": "bin/server/jvm.dll",
    "linux": "lib/server/libjvm.so",
    "macos": "lib/server/libjvm.dylib",
}


def verify(tree: Path, operating_system: str) -> list[str]:
    """`relocate.verify`, less the one reference a JDK resolves in a way no file search can model.

    **Every library in a JDK imports the VM by bare name and none of them can find it by searching.**
    Measured on 25.0.4.1 for Windows x64: `java.dll`, `net.dll`, `zip.dll` and nine more import
    `jvm.dll`, which is in `bin/server/`, a directory no DLL search order includes. They work because
    the launcher loads the VM **by path** before it loads any of them — `jli` reads `lib/jvm.cfg`,
    picks `server`, and `LoadLibrary`s that file — and a loader asked for a module already in the
    process answers with that one. The same is true of `libjvm` on Unix.

    So exactly that complaint is set aside, and only when the VM is where the launcher will look for
    it. Every other unresolved or escaping reference still fails the check, including one to the VM
    from a tree whose `server/` is missing it.

    **On Linux, the system libraries in `LINUX_SYSTEM_LIBRARIES` are set aside too**, whether the
    runner's loader found them outside the tree or not at all: they are the machine's precondition,
    declared in `requires.libraries`, not something the tree was supposed to contain. A library that
    is not on that list still fails the check, which is what keeps the list honest.
    """
    prefix = home(tree, operating_system)
    vm = tree / f"{prefix}{JVM[operating_system]}"
    problems = relocate.verify(tree, directories=directories(operating_system))
    if not vm.is_file():
        return problems + [f"the VM is not at {prefix}{JVM[operating_system]}, where the launcher loads it"]
    unresolved_vm = re.compile(rf"[^:]+: (?:\S*/)?{re.escape(vm.name)} does not resolve")
    problems = [problem for problem in problems if not unresolved_vm.fullmatch(problem)]
    if operating_system == "linux":
        system = re.compile(r"[^:]+: (\S+) (?:does not resolve|resolves outside the tree, to \S+)")
        problems = [
            problem for problem in problems
            if not ((match := system.fullmatch(problem))
                    and Path(match.group(1)).name in LINUX_SYSTEM_LIBRARIES)
        ]
    return problems


def system_libraries(tree: Path) -> list[str]:
    """The sonames the JDK's own files name and neither ship nor count as the C runtime.

    Read out of each file's dynamic section with `readelf -d`, not out of `ldd`, because `ldd`
    answers with everything the runner's loader pulled in — `libXau` through `libX11`, `libmd` through
    `libbsd` — and those are the distribution's business, not this archive's. What is declared is what
    Microsoft linked against. Anything outside `LINUX_SYSTEM_LIBRARIES` is refused: a new dependency
    in a new release is a precondition somebody has to read before it is published.
    """
    files = relocate.machine_files(tree, directories=directories("linux"))
    shipped = {path.name for path in tree.rglob("*.so*")}
    needed: set[str] = set()
    for path in files:
        listing = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True,
                                 check=True).stdout
        needed.update(re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", listing))
    external = sorted(
        name for name in needed
        if name not in shipped and name not in relocate.SYSTEM_SONAMES
        and not name.startswith("ld-linux")
    )
    unknown = [name for name in external if name not in LINUX_SYSTEM_LIBRARIES]
    if unknown:
        raise SystemExit(
            f"this JDK links {', '.join(unknown)} from the system, which no release measured before "
            f"did. Add it to LINUX_SYSTEM_LIBRARIES with the reason, or find out why it is new."
        )
    print(f"expects the system to provide {', '.join(external)}")
    return external


def smoke(tree: Path, version: str, manifest: dict, target: tuple[str, str]) -> dict:
    """Run the JDK from somewhere it has never been, and make every provided command do its job.

    `java --version` alone proves a launcher. What breaks in a moved JDK is everything found relative
    to it — `lib/modules`, the CDS archives, `lib/security/cacerts`, `jmods/` — so each is reached by
    the command that reads it: `javac` and `java` compile and run a program that reports its own
    `java.home` and version, `keytool` lists the CA certificates a TLS connection would trust, and
    `jlink` builds a runtime out of `jmods/` that itself has to start.
    """
    operating_system = target[0]
    elsewhere = borrow.moved(tree)

    problems = verify(elsewhere, operating_system)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        raise SystemExit("the relocated tree reaches outside itself")

    provides = manifest["provides"]
    java = elsewhere / provides["java"]
    path = borrow.clean_path(java.parent)
    work = borrow.long_name(Path(tempfile.mkdtemp(prefix="mixengine-java-")))

    def run(program: Path, *args: str) -> str:
        return borrow.run(program, *args, path=path, drop=FOREIGN)

    banner = run(java, "--version")
    if "Microsoft" not in banner:
        raise SystemExit(f"java --version does not name Microsoft's build:\n{banner}")

    source = work / "Hello.java"
    source.write_text(PROGRAM, encoding="utf-8", newline="\n")
    classes = work / "classes"
    run(elsewhere / provides["javac"], "-d", str(classes), str(source))
    said = run(java, "-cp", str(classes), "Hello").splitlines()

    stated = list(borrow.parts(version))
    while len(stated) > 1 and stated[-1] == 0:
        stated.pop()
    expected = [str(Path(java).parent.parent), str(stated), hashlib.sha256(b"mixengine").hexdigest()]
    if len(said) != 3 or said[1:] != expected[1:] or not Path(said[0]).samefile(expected[0]):
        raise SystemExit(f"the compiled program printed {said}, expected {expected}")

    for name in ("jar", "jshell"):
        run(elsewhere / provides[name], "--version")

    listed = run(elsewhere / provides["keytool"], "-list", "-cacerts", "-storepass", "changeit")
    trusted = re.search(r"contains (\d+) entr", listed)
    if not trusted or int(trusted.group(1)) == 0:
        raise SystemExit(f"keytool found no CA certificates in the moved JDK:\n{listed[:400]}")

    runtime = work / "runtime"
    run(elsewhere / provides["jlink"], "--add-modules", "java.base", "--output", str(runtime))
    linked = runtime / "bin" / java.name
    run(linked, "--version")

    borrow.discard(elsewhere)
    shutil.rmtree(work, ignore_errors=True)
    return {
        "relocated": True,
        "ran": [
            f"{provides['java']} --version, naming Microsoft",
            f"{provides['javac']} and {provides['java']}: a program reporting java.home, "
            "Runtime.version() and a SHA-256",
            f"{provides['jar']} --version",
            f"{provides['jshell']} --version",
            f"{provides['keytool']} -list -cacerts: {trusted.group(1)} CA certificates",
            f"{provides['jlink']} --add-modules java.base, and the linked runtime's java --version",
        ],
    }


def published_hash(checksums_url: str, archive_name: str) -> str:
    """The SHA-256 in Microsoft's ``.sha256sum.txt`` beside the archive: ``<digest>  <name>``."""
    text = borrow.fetch(checksums_url, headers=AGENT).decode("utf-8", "replace")
    for line in text.splitlines():
        digest, _, name = line.strip().partition("  ")
        if name.strip().lstrip("*") == archive_name and len(digest) == 64:
            return digest.lower()
    raise SystemExit(f"{checksums_url} states no SHA-256 for {archive_name}: {text[:200]!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", required=True,
        help="an LTS line (21), an exact version (21.0.12.1), or 'latest'. 11 upwards.",
    )
    parser.add_argument("--out", default="dist", type=Path)
    args = parser.parse_args()

    target = borrow.host("Java")
    operating_system = target[0]
    entry = resolve(args.version, target)
    version = entry["version"]
    if version != args.version:
        print(f"{args.version} resolved to {version} ({entry['release']})")
    eol.announce("java", version)

    suffix = TARGETS[target][3]
    archive_name = entry["url"].rsplit("/", 1)[-1]
    stated = published_hash(entry["checksums"], archive_name)
    if stated != entry["sha256"]:
        raise SystemExit(
            f"Microsoft's two statements of {archive_name} disagree: the marketplace entry says "
            f"{entry['sha256']}, the .sha256sum.txt beside it says {stated}"
        )

    work = Path(tempfile.mkdtemp(prefix="mixengine-java-"))
    downloaded = work / archive_name
    print(f"borrowing {entry['url']}")
    try:
        urllib.request.urlretrieve(entry["url"], downloaded)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{entry['url']} answered {error.code}") from error

    actual = borrow.sha256(downloaded)
    if actual != entry["sha256"]:
        raise SystemExit(f"sha256 mismatch: got {actual}, Microsoft states {entry['sha256']}")
    print(f"sha256 {actual} (verified against the marketplace entry and .sha256sum.txt)")

    tree = borrow.unpack(downloaded, work / "unpacked", suffix)
    removed = prune(tree, operating_system)
    # Expected to change nothing: no binary of any cell measured before this was written carried
    # debug information. Called anyway, so a cell that differs is declared rather than refused.
    changed = strip.debug(tree)

    manifest = describe(tree, entry, target, removed, changed)
    manifest["smoke"] = smoke(tree, version, manifest, target)

    if operating_system == "windows":
        needed = vcredist(tree)
        if needed:
            manifest["requires"] = {"vcredist": needed}
            print(f"needs the Visual C++ {needed} redistributable")
    else:
        requires = {}
        measured = relocate.floor(tree, directories=directories(operating_system))
        if measured:
            requires[measured[0]] = measured[1]
            print(f"needs {measured[0]} {measured[1]} or newer")
        if operating_system == "linux":
            requires["libraries"] = system_libraries(tree)
        if requires:
            manifest["requires"] = requires

    borrow.publish(tree, manifest, args.out, suffix)
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
