#!/usr/bin/env python3
"""Compile Valkey from upstream source, the Redis row's BSD continuation.

**Why this row exists.** The Redis row's floor is 7.2 because 7.2 is the last BSD-3 Redis; 7.4 is
RSALv2/SSPLv1 and 8.0 adds AGPLv3. Valkey forked from Redis 7.2.4 in March 2024 and is BSD-3-Clause
on every line, so it is where a user who needs a permissive in-memory store past 7.2 goes. It is its
own kind rather than a substitute inside `redis`: P8 refused Valkey as a way to fill Redis's Windows
cell, and that refusal was right — one version cannot mean two programs.

**The build is Redis's, and so is the code that knows how.** Finding Cygwin and proving it is Cygwin,
running a script under it with its own tools on `PATH`, reading `DEPENDENCY_TARGETS` out of the
tarball, the two compiler flags Cygwin's headers need — all of that is imported from `redis.py`, so
one runtime's quirks live in one file. What is Valkey's is here: the names, `USE_REDIS_SYMLINKS=no`,
the licence table, and a smoke test that asks for `valkey_version` rather than the `redis_version`
every line also reports for client compatibility.

**Core only, no TLS, no RDMA** — the Redis row's choices for the Redis row's reasons, repeated so the
two rows answer the same questions the same way.

**The version and its digest come from one document**: `valkey-io/valkey-hashes`, upstream's catalogue
in exactly `redis-hashes`' format, one `hash <file> sha256 <digest> <url>` line per tarball.

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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import redis  # noqa: E402
import relocate  # noqa: E402
import strip  # noqa: E402

HASHES = "https://raw.githubusercontent.com/valkey-io/valkey-hashes/main/README"

# Named for the same reason `redis.py` names itself: a publisher entitled to block a default agent is
# entitled to know which program is asking instead.
AGENT = redis.AGENT

# The oldest line: the one Valkey forked, and still patched upstream.
FLOOR = (7, 2)

SUFFIX = ".exe" if sys.platform == "win32" else ""

# The four names the Redis row provides, in Valkey's spelling. The check tools are copies of the
# server that pick their behaviour from `argv[0]`, which upstream's own rules make.
LAYOUT = {
    name: f"bin/{name}{SUFFIX}"
    for name in ("valkey-server", "valkey-cli", "valkey-check-rdb", "valkey-check-aof")
}

# Make goals on Windows, where `install` cannot run for Redis's reason — see `redis.WINDOWS_TARGETS`.
WINDOWS_TARGETS = ("valkey-server", "valkey-cli", "valkey-check-rdb", "valkey-check-aof")

# **Every line's `src/Makefile` says `USE_REDIS_SYMLINKS?=yes`**, which makes `install` add
# `redis-server`, `redis-cli` and the rest as links to the Valkey binaries. They would collide with
# the `redis` kind on a `PATH`, so upstream's own switch turns them off, on every goal.
MAKE_OPTIONS = ("USE_REDIS_SYMLINKS=no",)

# Installed and thrown away, for the Redis row's reasons: a benchmark, and a failover monitor for a
# replica set MixEngine never runs.
PRUNE = (f"bin/valkey-benchmark{SUFFIX}", f"bin/valkey-sentinel{SUFFIX}")

# Where each `deps/` directory keeps its licence. A tuple where the file moved between lines:
# `fast_float` has no licence file, and its MIT text is the header of `fast_float.h` on 8.1 and 9.0
# and of `ffc.h` from 9.1. As in `redis.py`, a directory with no row stops the build.
DEPS_LICENCES = {
    "fast_float": ("fast_float.h", "ffc.h"),
    "fpconv": ("LICENSE.txt",),
    "hdr_histogram": ("COPYING.txt",),
    "hiredis": ("COPYING",),
    "jemalloc": ("COPYING",),
    "libvalkey": ("COPYING",),
    "linenoise": ("linenoise.c",),
    "lua": ("COPYRIGHT",),
}

# In `deps/` and not redistributed code with a licence of its own, each for a stated reason. Named
# rather than skipped by pattern, so a new directory still fails the build.
NOT_REDISTRIBUTED = {
    # One `.cpp` of Valkey's own, compiled only with `USE_FAST_FLOAT=yes`, which is off by default;
    # covered by Valkey's `COPYING` either way.
    "fast_float_c_interface": "Valkey's own source, not built by default",
    # A Python script that runs Valkey's C++ unit tests in parallel. Compiled into nothing.
    "gtest-parallel": "a test runner, compiled into nothing",
}


def catalogue() -> dict[tuple[int, ...], tuple[str, str, str]]:
    """Every stable release upstream has published, as ``version -> (version, url, sha256)``.

    Release candidates (``valkey-9.2.0-rc1.tar.gz``) share the file and are not releases, so the
    pattern insists on three numeric components.
    """
    listing = borrow.fetch(HASHES, headers=AGENT).decode("utf-8", "replace")
    offered: dict[tuple[int, ...], tuple[str, str, str]] = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] != "hash" or fields[2] != "sha256":
            continue
        match = re.fullmatch(r"valkey-(\d+\.\d+\.\d+)\.tar\.gz", fields[1])
        if not match:
            continue
        key = borrow.parts(match.group(1))
        if key[:2] < FLOOR:
            continue
        url = fields[4]
        if not url.startswith("https://"):
            url = "https://" + url.partition("://")[2]
        offered[key] = (match.group(1), url, fields[3])
    if not offered:
        raise SystemExit(f"{HASHES} listed no valkey-<x.y.z>.tar.gz at all; upstream changed its shape")
    return offered


def resolve(spec: str) -> tuple[str, str, str]:
    """Turn ``9``, ``9.1``, ``9.1.2`` or ``latest`` into one published tarball and its digest."""
    offered = catalogue()
    if spec == "latest":
        candidates = sorted(offered)
    else:
        prefix = borrow.parts(spec)
        candidates = sorted(key for key in offered if key[: len(prefix)] == prefix)
    if not candidates:
        lines = [".".join(map(str, line)) for line in sorted({key[:2] for key in offered})]
        raise SystemExit(
            f"valkey-hashes lists no stable {spec} at or above {'.'.join(map(str, FLOOR))}. "
            f"It offers {', '.join(lines)}."
        )
    return offered[candidates[-1]]


def source(spec: str, work: Path) -> tuple[str, Path, str, str]:
    """Fetch and unpack the release tarball, checked against the digest the catalogue states."""
    version, url, digest = resolve(spec)
    if version != spec:
        print(f"{spec} resolves to Valkey {version}")

    tarball = work / f"valkey-{version}.tar.gz"
    print(f"fetching {url}")
    tarball.write_bytes(borrow.fetch(url, timeout=1800, headers=AGENT))
    actual = borrow.sha256(tarball)
    if actual != digest:
        raise SystemExit(f"{tarball.name} hashes to {actual}, valkey-hashes states {digest}")
    print(f"sha256 {actual} (verified against valkey-io/valkey-hashes)")

    with tarfile.open(tarball) as archive:
        archive.extractall(work, filter="data")
    unpacked = work / f"valkey-{version}"
    if not (unpacked / "src" / "Makefile").is_file():
        raise SystemExit(f"{unpacked} has no src/Makefile; this is not a Valkey release tarball")
    return version, unpacked, actual, url


def build_windows(source_tree: Path, prefix: Path) -> list[str]:
    """Compile the core under Cygwin, the way `redis.build_windows` does, and copy out four binaries."""
    root = redis.cygwin_root()
    print(f"building under Cygwin at {root}")
    targets = redis.dependency_targets(source_tree)
    options = " ".join(MAKE_OPTIONS)
    redis.cygwin(
        root,
        f'set -e\n'
        f'make -C deps -j{redis.jobs()} CFLAGS="{redis.WINDOWS_CFLAGS}" {" ".join(targets)}\n'
        f'make -C src -j{redis.jobs()} CFLAGS="{redis.WINDOWS_CFLAGS}" {options} '
        f'{" ".join(WINDOWS_TARGETS)}\n',
        cwd=source_tree,
    )
    binaries = prefix / "bin"
    binaries.mkdir(parents=True, exist_ok=True)
    for name in WINDOWS_TARGETS:
        built = source_tree / "src" / f"{name}.exe"
        if not built.is_file():
            raise SystemExit(f"the build produced no {built.name}; make reported success")
        shutil.copy2(built, binaries / built.name)
    return [
        f"make -C deps {' '.join(targets)} (Cygwin)",
        f"make -C src {' '.join(WINDOWS_TARGETS)} {options} CFLAGS={redis.WINDOWS_CFLAGS!r}",
    ]


def build(source_tree: Path, prefix: Path) -> list[str]:
    """Compile the core and install it, and answer with what was asked for.

    ``make -C src``, as for Redis: the core's own Makefile, with TLS and RDMA at upstream's default of
    off and the `redis-*` links switched off by name.
    """
    if sys.platform == "win32":
        return build_windows(source_tree, prefix)
    redis.run("make", "-C", "src", f"-j{redis.jobs()}", "all", *MAKE_OPTIONS, cwd=source_tree)
    redis.run("make", "-C", "src", "install", f"PREFIX={prefix}", *MAKE_OPTIONS, cwd=source_tree)
    options = " ".join(MAKE_OPTIONS)
    return [f"make -C src all {options}", f"make -C src install PREFIX={prefix.name} {options}"]


def licences(tree: Path, source_tree: Path) -> list[str]:
    """Ship Valkey's licence and the licence of everything compiled into it, having checked the list."""
    into = tree / "licenses"
    into.mkdir(exist_ok=True)
    shipped: list[str] = []

    own = source_tree / "COPYING"
    if not own.is_file():
        raise SystemExit("the tarball carries no COPYING; nothing states the terms of this archive")
    shutil.copy2(own, into / "valkey-COPYING")
    shipped.append("valkey-COPYING")

    deps = source_tree / "deps"
    present = sorted(path.name for path in deps.iterdir() if path.is_dir())
    unknown = [name for name in present if name not in DEPS_LICENCES and name not in NOT_REDISTRIBUTED]
    if unknown:
        raise SystemExit(
            f"deps/ carries {', '.join(unknown)}, which neither DEPS_LICENCES nor NOT_REDISTRIBUTED "
            f"names — this build would redistribute code whose licence it has not looked for. Add a row."
        )
    for name in present:
        if name in NOT_REDISTRIBUTED:
            continue
        found = [deps / name / candidate for candidate in DEPS_LICENCES[name]
                 if (deps / name / candidate).is_file()]
        if not found:
            raise SystemExit(
                f"deps/{name} has none of {', '.join(DEPS_LICENCES[name])}; upstream moved its "
                f"licence and the row has to move with it"
            )
        shutil.copy2(found[0], into / f"valkey-deps-{name}-{found[0].name}")
        shipped.append(f"valkey-deps-{name}-{found[0].name}")

    print(f"shipping {len(shipped)} licence file(s) for Valkey and its bundled deps")
    return shipped


def assemble(prefix: Path, work: Path, source_tree: Path) -> tuple[Path, dict[str, str]]:
    """The installed prefix as the tree that will be packed, minus what does not ship."""
    tree = work / "tree"
    shutil.copytree(prefix, tree, symlinks=True)

    dropped = []
    for relative in PRUNE:
        if os.path.lexists(tree / relative):
            (tree / relative).unlink()
            dropped.append(relative)
    if dropped:
        print(f"not shipping {', '.join(dropped)}")

    redis_names = sorted(path.name for path in (tree / "bin").iterdir() if path.name.startswith("redis-"))
    if redis_names:
        raise SystemExit(
            f"the install left {', '.join(redis_names)} in bin/ although USE_REDIS_SYMLINKS=no was "
            f"passed; upstream changed the switch and the archive would collide with the redis kind"
        )

    provides = {name: path for name, path in LAYOUT.items() if os.path.lexists(tree / path)}
    missing = sorted(set(LAYOUT) - set(provides))
    if missing:
        raise SystemExit(
            f"the build installed no {', '.join(missing)}. Installed: "
            f"{sorted(path.name for path in (tree / 'bin').iterdir())}"
        )
    licences(tree, source_tree)
    return tree, provides


def await_pong(cli: Path, port: int, process: subprocess.Popen, log: Path,
               environment: dict, seconds: float = 30) -> None:
    """Wait for the server to answer ``PING``, or say what it said instead."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(
                f"valkey-server exited {process.returncode} before it answered PING\n"
                f"{log.read_text(encoding='utf-8', errors='replace')}"
            )
        answer = subprocess.run([str(cli), "-p", str(port), "ping"], capture_output=True, text=True,
                                timeout=30, env=environment)
        if answer.returncode == 0 and answer.stdout.strip() == "PONG":
            return
        time.sleep(0.2)
    process.kill()
    raise SystemExit(
        f"valkey-server never answered PING on {port}\n{log.read_text(encoding='utf-8', errors='replace')}"
    )


def smoke(tree: Path, version: str, provides: dict[str, str]) -> dict:
    """Run the artifact from somewhere it has never been, and make it be a cache while there.

    Redis's test with Valkey's names, and two differences. `INFO server` is read for
    `valkey_version`, because every line also reports a `redis_version` for clients — 7.2.4 on the 7.2
    line — which is not this archive's version. And an `EVAL` runs, because from 9.1 the Lua engine is
    a module linked into the server rather than part of it, and a build that lost it would still answer
    `PING` and `GET`.

    The configuration is written with a quoted `dir` and named relatively against a working directory,
    for the two reasons `redis.smoke` gives: a path with a space, and Cygwin's idea of an absolute path.
    """
    elsewhere = borrow.moved(tree)
    problems = relocate.verify(elsewhere)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        raise SystemExit("the relocated tree reaches outside itself")

    server = elsewhere / provides["valkey-server"]
    cli = elsewhere / provides["valkey-cli"]
    path = borrow.clean_path(server.parent)

    banner = borrow.run(server, "--version", path=path)
    if f"v={version} " not in banner:
        raise SystemExit(f"valkey-server reports {banner!r}, expected a v={version} build")
    print(f"valkey-server: {banner}")

    port = redis.free_port()
    work = elsewhere.parent / "instance"
    work.mkdir(parents=True, exist_ok=True)
    config = work / "valkey.conf"
    config.write_text(
        f"bind 127.0.0.1\n"
        f"port {port}\n"
        f"dir \"{work.as_posix()}\"\n"
        f"save \"\"\n"
        f"appendonly no\n"
        f"daemonize no\n",
        encoding="utf-8",
    )

    log = work / "valkey.log"
    environment = {**os.environ, "PATH": path}
    with log.open("wb") as sink:
        process = subprocess.Popen([str(server), config.name], stdout=sink, stderr=subprocess.STDOUT,
                                   env=environment, cwd=str(work))

    def cli_run(*args: str) -> str:
        return borrow.run(cli, "-p", str(port), *args, path=path)

    try:
        await_pong(cli, port, process, log, environment)
        print(f"valkey-cli ping: PONG on {port}")

        info = cli_run("info", "server")
        reported = dict(line.split(":", 1) for line in info.splitlines()
                        if ":" in line and not line.startswith("#"))
        if reported.get("valkey_version", "").strip() != version:
            raise SystemExit(
                f"the server on {port} reports valkey_version {reported.get('valkey_version')!r}; "
                f"this archive is {version}"
            )
        print(f"valkey-cli info server: valkey_version {version}")

        expected = f"mixengine {version}"
        cli_run("set", "mixengine:smoke", expected)
        stored = cli_run("get", "mixengine:smoke")
        if stored != expected:
            raise SystemExit(f"GET answered {stored!r}, expected {expected!r}")

        scripted = cli_run("eval", "return ARGV[1]", "0", expected)
        if scripted != expected:
            raise SystemExit(f"EVAL answered {scripted!r}; the Lua engine is not doing its job")
        print(f"valkey-cli set/get/eval: {stored}")

        subprocess.run([str(cli), "-p", str(port), "shutdown", "nosave"], capture_output=True,
                       text=True, timeout=60, env=environment)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            raise SystemExit("valkey-cli shutdown returned and the server was still running") from None
        print("valkey-cli shutdown nosave: the server exited")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)

    borrow.discard(elsewhere)
    return {
        "relocated": True,
        "ran": [
            "bin/valkey-server --version",
            "valkey-server against a rendered valkey.conf",
            "valkey-cli ping",
            "valkey-cli info server, valkey_version checked against this archive's version",
            "valkey-cli set/get",
            "valkey-cli eval, which the Lua engine answers",
            "valkey-cli shutdown nosave",
        ],
    }
