#!/usr/bin/env python3
"""Compile Apache httpd on every cell, because nothing publishable exists to borrow.

**Why built everywhere.** The Apache Software Foundation publishes source only. The Windows build
everybody uses is Apache Lounge's, and it fails every test a borrow here has to pass: its digests
are sent by mail on request, one build is kept at a time, the same httpd version is rebuilt under a
date suffix against newer dependencies, redistribution is not addressed, and there is no ARM64
build. The evaluation is in ``docs/superpowers/specs/2026-09-17-httpd-packaging-design.md``.

**One version means one module set, chosen here.** With no borrowed build to act as the
specification — nginx has upstream's Windows ``nginx -V`` — :data:`MODULES` *is* the
specification, and every cell is checked against it twice: at build time by
:func:`check_modules`, and after relocation by ``httpd -M`` in :mod:`httpd_smoke`. Every module is
built shared, so a rendered configuration turns each one on or off; the MPM and the platform glue
(``event`` and ``unixd`` on Unix, ``mpm_winnt`` and ``win32`` on Windows) are compiled into the
server and are therefore not in ``extensions``, which is what keeps them out of `parity.py`'s
comparison — they are httpd's asymmetry, not this recipe's.

**PHP reaches it through ``mod_proxy_fcgi``**, never ``mod_php``: the PHP rows are non-thread-safe
on Windows and ``static-php-cli`` builds no ``apache2handler`` on Unix.

This file is the Unix recipe and everything both recipes share — the catalogue, the pinned
libraries, the module set, the licences and the prune. ``httpd_build.py`` is Windows.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import nginx  # noqa: E402
import relocate  # noqa: E402
import strip  # noqa: E402

CURRENT = "https://downloads.apache.org/httpd"
ARCHIVE = "https://archive.apache.org/dist/httpd"

# The only line upstream maintains; 2.2 has been dead since 2017.
LINE = (2, 4)

# **The same OpenSSL, PCRE2 and zlib as the nginx row**, taken from `nginx.py` rather than pinned a
# second time, so the two web servers of one index release carry the same TLS library. The other
# four are httpd's own: APR and APR-util from the ASF, whose `.sha256` beside each tarball is what
# these digests were checked against when they were pinned; nghttp2 for `mod_http2` and expat for
# APR-util, whose digests are the GitHub release asset digests of the tarballs named here.
LIBRARIES = {
    **nginx.LIBRARIES,
    "nghttp2": {
        "version": "1.70.0",
        "url": "https://github.com/nghttp2/nghttp2/releases/download/v1.70.0/nghttp2-1.70.0.tar.gz",
        "sha256": "aa317e2cf9dca6afa0aed68f8fad6ff303ec6982e25a78c75c0b65e2b9b3ded5",
        "licence": ("COPYING", "nghttp2-COPYING"),
    },
    "expat": {
        "version": "2.8.4",
        "url": "https://github.com/libexpat/libexpat/releases/download/R_2_8_4/expat-2.8.4.tar.gz",
        "sha256": "b8ece2437692dad44d851c4532723390a5a330990007706be9c8d2b90d294f36",
        "licence": ("COPYING", "expat-COPYING"),
    },
    "apr": {
        "version": "1.7.6",
        "url": "https://downloads.apache.org/apr/apr-1.7.6.tar.gz",
        "sha256": "6a10e7f7430510600af25fabf466e1df61aaae910bf1dc5d10c44a4433ccc81d",
        "licence": ("LICENSE", "apr-LICENSE"),
    },
    "apr-util": {
        "version": "1.6.5",
        "url": "https://downloads.apache.org/apr/apr-util-1.6.5.tar.gz",
        "sha256": "f43a1c8c79eef497a022ec6c99dddbdf57e42001da6ccbfae259631ed5aa2805",
        "licence": ("LICENSE", "apr-util-LICENSE"),
    },
}

# **The specification.** Serving, access control that `.htaccess` files written for 2.2 still use,
# and PHP and TLS. Named without the `mod_` prefix, the spelling `LoadModule` and CMake's
# `ENABLE_<NAME>` use.
MODULES = (
    "access_compat", "alias", "authz_core", "authz_host", "deflate", "dir", "env", "expires",
    "filter", "headers", "http2", "log_config", "mime", "proxy", "proxy_fcgi", "rewrite",
    "setenvif", "socache_shmcb", "ssl", "vhost_alias",
)

# Compiled into the Unix server rather than chosen: dynamic loading, the HTTP protocol, and the
# privilege handling every Unix MPM needs.
SERVER = ("http", "so", "unixd")

# Where `LoadModule` finds each one, relative to the server root, on every cell.
EXTENSION_DIR = "modules"

LICENCES = ("httpd-LICENSE", "httpd-NOTICE", *sorted(
    shipped for _, shipped in (described["licence"] for described in LIBRARIES.values())
))


def run(*command: str, cwd: Path | None = None, env: dict | None = None,
        timeout: int = 5400) -> None:
    """Run a build step, finding the program on *env*'s ``PATH`` rather than this process's.

    ``CreateProcess`` searches the *parent's* ``PATH`` for a bare name, so on Windows ``nmake`` inside
    a captured developer environment is not found at all, and ``cmake`` is found — the runner's,
    rather than the one that environment selected.
    """
    print("$ " + " ".join(str(part) for part in command), flush=True)
    program = str(command[0])
    if env is not None and not Path(program).is_absolute():
        program = shutil.which(program, path=env.get("PATH")) or program
    result = subprocess.run([program, *(str(part) for part in command[1:])], cwd=cwd, env=env,
                            timeout=timeout)
    if result.returncode != 0:
        raise SystemExit(f"{Path(str(command[0])).name} exited {result.returncode}")


def jobs() -> str:
    return str(os.cpu_count() or 2)


# ----------------------------------------------------------------------------- the catalogue


def catalogue() -> dict[tuple[int, ...], str]:
    """Every 2.4 release either ASF host lists, as ``version -> base URL``.

    ``downloads.apache.org`` carries the current release and ``archive.apache.org`` every release
    ever made, so the current one is fetched from the mirror network's origin and the rest from the
    archive — which is also why a version a blueprint pinned never stops resolving.
    """
    offered: dict[tuple[int, ...], str] = {}
    for base in (ARCHIVE, CURRENT):
        try:
            listing = borrow.fetch(f"{base}/").decode("utf-8", "replace")
        except urllib.error.URLError as error:
            if base == ARCHIVE:
                print(f"{ARCHIVE}: {error}; resolving against the current release only")
                continue
            raise
        for version in re.findall(r'href="httpd-(\d+\.\d+\.\d+)\.tar\.gz"', listing):
            key = borrow.parts(version)
            if key[:2] == LINE:
                offered[key] = base
    if not offered:
        raise SystemExit(f"{CURRENT}/ listed no httpd-2.4.<n>.tar.gz; the listing changed shape")
    return offered


def resolve(spec: str) -> tuple[str, str]:
    """Turn ``2``, ``2.4``, ``2.4.68`` or ``latest`` into ``(version, tarball URL)``."""
    offered = catalogue()
    if spec == "latest":
        candidates = sorted(offered)
    else:
        prefix = borrow.parts(spec)
        candidates = sorted(key for key in offered if key[: len(prefix)] == prefix)
    if not candidates:
        newest = ".".join(map(str, max(offered)))
        raise SystemExit(f"the ASF publishes no httpd {spec}; the 2.4 line's newest is {newest}")
    key = candidates[-1]
    version = ".".join(map(str, key))
    return version, f"{offered[key]}/httpd-{version}.tar.gz"


def source(spec: str, work: Path) -> tuple[str, Path, str, str]:
    """Fetch and unpack the release tarball, checked against the ``.sha512`` beside it.

    Answers ``(version, source tree, sha256, url)``: the manifest's field is a SHA-256 of the same
    bytes, and which digest the download was *checked* with is recorded in the recipe line.
    """
    version, url = resolve(spec)
    if version != spec:
        print(f"{spec} resolves to httpd {version}")
    tarball = work / f"httpd-{version}.tar.gz"
    print(f"fetching {url}")
    tarball.write_bytes(borrow.fetch(url, timeout=1800))
    try:
        stated = borrow.fetch(f"{url}.sha512").decode("ascii", "replace").split()[0].lower()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{url}.sha512 answered {error.code}; nothing states this tarball") from error
    actual = borrow.sha512(tarball)
    if actual != stated:
        raise SystemExit(f"{tarball.name} hashes to sha512 {actual}, the ASF states {stated}")
    print(f"sha512 verified against {url}.sha512")

    with tarfile.open(tarball) as archive:
        archive.extractall(work, filter="data")
    unpacked = work / f"httpd-{version}"
    if not (unpacked / "include" / "ap_release.h").is_file():
        raise SystemExit(f"{unpacked} has no include/ap_release.h; this is not an httpd tarball")
    return version, unpacked, borrow.sha256(tarball), url


def libraries(work: Path) -> dict[str, Path]:
    """Fetch every pinned library, refuse any whose bytes are not the pinned ones, and unpack it."""
    unpacked: dict[str, Path] = {}
    for library, described in LIBRARIES.items():
        tarball = work / "downloads" / f"{library}.tar.gz"
        tarball.parent.mkdir(parents=True, exist_ok=True)
        print(f"fetching {described['url']}")
        tarball.write_bytes(borrow.fetch(described["url"], timeout=1800))
        actual = borrow.sha256(tarball)
        if actual != described["sha256"]:
            raise SystemExit(
                f"{library} {described['version']} hashes to {actual}, this recipe pins "
                f"{described['sha256']} — the bytes at that URL are not the ones it was written against"
            )
        into = work / "libraries" / library
        with tarfile.open(tarball) as archive:
            archive.extractall(into, filter="data")
        entries = [path for path in into.iterdir() if path.is_dir()]
        if len(entries) != 1:
            raise SystemExit(f"{library}'s tarball holds {[path.name for path in into.iterdir()]}")
        unpacked[library] = entries[0]
        print(f"  {library} {described['version']} verified against the pinned digest")
    return unpacked


# ----------------------------------------------------------------------------- the Unix build


def dependencies(unpacked: dict[str, Path], deps: Path, operating_system: str) -> dict[str, str]:
    """Build the five libraries as static, position-independent archives into *deps*.

    **Static, so the tree carries none of them as files of their own** — the shape the nginx row's
    compiled cells have — and **position-independent**, because every one of them is linked into a
    shared object: OpenSSL into ``mod_ssl.so``, zlib into ``mod_deflate.so``, nghttp2 into
    ``mod_http2.so``, expat into ``libaprutil-1``. A non-PIC ``libz.a`` links into an executable and
    is refused by the linker in a shared module on x86_64 Linux.

    Answers the environment httpd's ``configure`` needs to find them.
    """
    environment = dict(os.environ) | {"CFLAGS": "-O2 -fPIC"}
    prefix = f"--prefix={deps}"

    run("./configure", "--static", prefix, cwd=unpacked["zlib"], env=environment)
    run("make", f"-j{jobs()}", "install", cwd=unpacked["zlib"], env=environment)

    run("./configure", prefix, "--disable-shared", "--with-pic", "--disable-pcre2grep-libz",
        "--disable-pcre2grep-libbz2", "--disable-jit", cwd=unpacked["pcre2"], env=environment)
    run("make", f"-j{jobs()}", "install", cwd=unpacked["pcre2"], env=environment)

    run("./configure", prefix, "--disable-shared", "--with-pic", "--without-xmlwf",
        "--without-examples", "--without-tests", "--without-docbook",
        cwd=unpacked["expat"], env=environment)
    run("make", f"-j{jobs()}", "install", cwd=unpacked["expat"], env=environment)

    run("./configure", prefix, "--disable-shared", "--with-pic", "--enable-lib-only",
        cwd=unpacked["nghttp2"], env=environment)
    run("make", f"-j{jobs()}", "install", cwd=unpacked["nghttp2"], env=environment)

    # `--libdir=lib` because OpenSSL installs into `lib64` on 64-bit Linux, where neither
    # pkg-config below nor httpd's `--with-ssl` would look. `no-shared` leaves PIC on: OpenSSL
    # compiles its static archive with the same flags as its shared one unless told `no-pic`.
    run("./Configure", prefix, "--libdir=lib", "no-shared", *nginx.OPENSSL_OPT.split(), "no-docs",
        cwd=unpacked["openssl"], env=environment)
    run("make", f"-j{jobs()}", cwd=unpacked["openssl"], env=environment, timeout=10800)
    run("make", "install_sw", cwd=unpacked["openssl"], env=environment)

    found = dict(os.environ) | {"PKG_CONFIG_PATH": str(deps / "lib" / "pkgconfig")}
    if operating_system == "linux":
        # A static libcrypto needs these at every link, and `pkg-config --libs` (without
        # `--static`) does not say so; httpd's OpenSSL check is a link test and would fail on it.
        found["LIBS"] = "-ldl -pthread"
    return found


def configurable(source_tree: Path) -> list[str]:
    """Every module httpd's ``configure`` offers a switch for, read out of the script itself."""
    text = (source_tree / "configure").read_text(encoding="utf-8", errors="replace")
    names = sorted(set(re.findall(r"checking whether to enable mod_(\w+)", text)))
    unknown = sorted(set(MODULES) - set(names))
    if not names or unknown:
        raise SystemExit(f"httpd's configure offers no switch for {', '.join(unknown) or 'any module'}")
    return names


def build(version: str, source_tree: Path, unpacked: dict[str, Path], prefix: Path,
          work: Path, operating_system: str) -> list[str]:
    """``configure``, ``make`` and ``make install`` httpd into *prefix*. Answers the arguments."""
    deps = work / "deps"
    environment = dependencies(unpacked, deps, operating_system)

    # `--with-included-apr` wants the two source trees under `srclib/` by these exact names.
    for library in ("apr", "apr-util"):
        shutil.copytree(unpacked[library], source_tree / "srclib" / library)

    arguments = [
        f"--prefix={prefix}",
        "--with-included-apr",
        f"--with-expat={deps}",
        f"--with-pcre={deps / 'bin' / 'pcre2-config'}",
        f"--with-ssl={deps}",
        f"--with-nghttp2={deps}",
        f"--with-z={deps}",
        "--with-mpm=event",
        # Named, because `--enable-modules=none` switches it off with everything else, and an
        # httpd without it refuses to accept a connection: AH00136, measured on both macOS cells.
        "--enable-unixd=static",
        "--enable-modules=none",
        f"--enable-mods-shared={' '.join(MODULES)}",
        # **Every other module off by name**, because `none` is not the whole answer: a module
        # whose default is its parent's follows the parent, so enabling `proxy` alone built fourteen
        # more — every balancer and every `proxy_*` protocol. `so`, `http` and `unixd` are the
        # server itself and stay compiled in.
        *(f"--disable-{name.replace('_', '-')}" for name in configurable(source_tree)
          if name not in MODULES and name not in SERVER),
        # APR-util reads these too, since httpd hands its arguments down to the bundled configure:
        # every optional database driver and LDAP off, so a runner's development packages decide
        # nothing about what the archive links.
        "--without-berkeley-db", "--without-gdbm", "--without-ndbm", "--without-sqlite3",
        "--without-pgsql", "--without-mysql", "--without-odbc", "--without-ldap",
        "--without-crypto",
    ]
    run("./configure", *arguments, cwd=source_tree, env=environment)
    run("make", f"-j{jobs()}", cwd=source_tree, env=environment)
    run("make", "install", cwd=source_tree, env=environment)
    return arguments


# ----------------------------------------------------------------------------- the tree


def assemble(prefix: Path, work: Path, windows: bool) -> Path:
    """The installed prefix as the tree that will be packed: what a running server reads, and no more.

    **Kept**: ``bin/httpd`` and, on Windows, every DLL beside it — libhttpd, APR, and the libraries
    this recipe built; ``lib/`` holding APR's shared libraries on Unix; ``modules/``; ``conf/``,
    whose ``mime.types`` a rendered configuration's ``TypesConfig`` names and whose default
    ``httpd.conf`` stays as upstream's reference; ``error/``, which that default includes.

    **Everything else goes**, and it is listed as it goes: the headers, import and static libraries,
    ``apxs`` and the build tree it needs, ``man/``, the sample ``htdocs/`` and ``cgi-bin/``,
    ``icons/`` (only ``mod_autoindex`` reads them and it is not in the set), the support programs no
    service recipe calls, and on Windows OpenSSL's own ``openssl.exe`` and install leftovers.
    """
    tree = work / "tree"
    shutil.copytree(prefix, tree, symlinks=True)
    removed: list[tuple[str, int]] = []

    def drop(path: Path) -> None:
        weight = path.stat().st_size if path.is_file() or path.is_symlink() else sum(
            item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink()
        )
        removed.append((path.relative_to(tree).as_posix(), weight))
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    roots = {"bin", "conf", "error", "modules"} | (set() if windows else {"lib"})
    for entry in sorted(tree.iterdir()):
        if entry.name not in roots:
            drop(entry)

    for entry in sorted((tree / "modules").iterdir()):
        if not (entry.name.startswith("mod_") and entry.suffix == ".so"):
            drop(entry)

    server = tree / "bin" / ("httpd.exe" if windows else "httpd")
    if windows:
        # A DLL ships when the server or a module loads it, directly or through another DLL — read
        # off the import tables, so `pcre2-posix.dll`, which PCRE2's CMake build installs and nothing
        # here imports, does not ride along with the ones that are needed.
        present = {entry.name.lower(): entry for entry in (tree / "bin").iterdir()
                   if entry.suffix.lower() == ".dll"}
        needed: set[Path] = set()
        queue = [server, *sorted((tree / "modules").glob("mod_*.so"))]
        while queue:
            for name in relocate.pe_imports(queue.pop()):
                found = present.get(name.lower())
                if found and found not in needed:
                    needed.add(found)
                    queue.append(found)
        kept = needed | {server}
    else:
        kept = {server}
    for entry in sorted((tree / "bin").iterdir()):
        if entry not in kept:
            drop(entry)
    if not windows:
        shared = re.compile(r"libapr(util)?-1\.(so(\.\d+)*|(\d+\.)*dylib)")
        for entry in sorted((tree / "lib").iterdir()):
            if not shared.fullmatch(entry.name):
                drop(entry)

    for relative, weight in removed:
        print(f"not shipping {relative} ({weight:,} bytes)")
    return tree


def check_modules(tree: Path) -> None:
    """Refuse a tree whose ``modules/`` is not exactly :data:`MODULES` — on every cell.

    A module missing is a directive that parses on five cells and not the sixth; a module gained is
    something one cell does that the row never decided on. Either way the build changed underneath
    the specification, and a person decides which of the two is wrong.
    """
    built = sorted(path.name[len("mod_"):-len(".so")] for path in (tree / "modules").glob("mod_*.so"))
    if built != sorted(MODULES):
        raise SystemExit(
            "this cell's modules are not the row's.\n"
            f"  built and not specified: {', '.join(sorted(set(built) - set(MODULES))) or 'nothing'}\n"
            f"  specified and not built: {', '.join(sorted(set(MODULES) - set(built))) or 'nothing'}"
        )
    print(f"the same {len(MODULES)} shared modules as every other cell")


def describe(version: str, target: tuple[str, str], url: str, digest: str, recipe: str) -> dict:
    """The manifest, up to what only the smoke test and the floor can add."""
    operating_system, arch = target
    return {
        "schema": 1,
        "kind": "httpd",
        "version": version,
        "os": operating_system,
        "arch": arch,
        "source": "built",
        "upstream": {
            "url": url,
            "sha256": digest,
            "verified_against": "the .sha512 the Apache Software Foundation publishes beside the tarball",
            "project": "apache/httpd",
        },
        "recipe": recipe,
        "provides": {"httpd": "bin/httpd.exe" if operating_system == "windows" else "bin/httpd"},
        "extension_dir": EXTENSION_DIR,
        "extensions": {"shared": sorted(MODULES)},
    }


def pinned() -> str:
    return ", ".join(f"{name} {described['version']}" for name, described in sorted(LIBRARIES.items()))


def collect_licences(tree: Path, source_tree: Path, unpacked: dict[str, Path]) -> None:
    """Ship httpd's licence and notice and the licence of every library built into the tree."""
    into = tree / "licenses"
    into.mkdir(exist_ok=True)
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(source_tree / name, into / f"httpd-{name}")
    for library, described in LIBRARIES.items():
        published, shipped = described["licence"]
        text = unpacked[library] / published
        if not text.is_file():
            raise SystemExit(
                f"{library} {described['version']} has no {published}; upstream moved its licence "
                f"and the row has to move with it"
            )
        shutil.copy2(text, into / shipped)
    held = sorted(path.name for path in into.iterdir() if path.is_file())
    if held != sorted(LICENCES):
        raise SystemExit(f"licenses/ holds {', '.join(held)} and this row ships {', '.join(LICENCES)}")
    print(f"shipping {len(held)} licence files")


def main() -> None:
    import httpd_smoke  # here rather than above: it imports this module

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="'2.4', an exact version, or 'latest'")
    parser.add_argument("--out", default=Path("dist"), type=Path)
    arguments = parser.parse_args()

    operating_system, arch = borrow.host("httpd")
    if operating_system == "windows":
        raise SystemExit("this is the Unix recipe; use tools/httpd_build.py")

    work = Path(tempfile.mkdtemp(prefix="mixengine-httpd-"))
    version, source_tree, digest, url = source(arguments.version, work)
    unpacked = libraries(work)
    print(f"packing httpd {version} for {operating_system}/{arch}")

    # A fixed prefix outside the work directory, as `mariadb_build.py` has: the path is compiled into
    # the binaries and every trace of it is removed by `relocate.bundle` below.
    prefix = Path("/opt/mixengine") / f"httpd-{version}"
    try:
        prefix.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        run("sudo", "mkdir", "-p", str(prefix))
        run("sudo", "chown", "-R", str(os.getuid()), str(prefix.parent))

    arguments_used = build(version, source_tree, unpacked, prefix, work, operating_system)
    # **The install prefix, not the tree**, and the order is forced twice over. `relocate.bundle`
    # below copies APR's libraries from the prefix over the tree's copies, so a tree stripped first
    # gets its debug information back; and a tree stripped *after* bundling has been through
    # `patchelf`, whose rewritten segments `strip` then changes in ways `strip.debug` rightly refuses.
    strip.debug(prefix)
    tree = assemble(prefix, work, windows=False)
    check_modules(tree)
    collect_licences(tree, source_tree, unpacked)

    # APR's two libraries are in the tree already and are rewritten to be found from it; what
    # `bundle` copies in from *outside* the install prefix is the machine's, and only those need a
    # licence found for them — APR's are collected above with the rest.
    bundled = relocate.bundle(tree, search=[prefix / "lib"])
    foreign = {name: origin for name, origin in bundled.items() if not relocate.inside(origin, prefix)}
    if foreign:
        print(f"bundled {len(foreign)} system librar{'y' if len(foreign) == 1 else 'ies'}: "
              f"{', '.join(sorted(foreign))}")
        relocate.bundled_licences(tree, foreign)

    manifest = describe(
        version, (operating_system, arch), url, digest,
        f"httpd-{version}.tar.gz from source (sha512 verified against the ASF's .sha512); configure "
        + " ".join(argument for argument in arguments_used
                   if not argument.startswith(("--prefix", "--disable-")))
        + f", every other module disabled; {pinned()} compiled in statically",
    )
    measured = relocate.floor(tree)
    if measured:
        manifest["requires"] = {measured[0]: measured[1]}
        print(f"needs {measured[0]} {measured[1]} or newer")

    manifest["smoke"] = httpd_smoke.smoke(tree, version, manifest)
    borrow.publish(tree, manifest, arguments.out, "tar")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
