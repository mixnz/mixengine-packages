#!/usr/bin/env python3
"""Build MSYS2 with the toolchain RubyInstaller's ``ridk install 3`` would add, as a MixEngine package.

**Why this exists.** Ruby for Windows is RubyInstaller's, and it carries no compiler: ``gem install``
of a gem with a C extension answers ``MSYS2 could not be found`` (see ``docs/packages/ruby.md`` and
``ruby_parity.LACKS``). MixEngine installs this package into its home and its shim points every Ruby
at it through ``MSYS2_PATH``, the first place RubyInstaller looks.

**Built, not fetched at install time.** The base is unpacked, initialised, updated and given the
toolchain here, on the runner, so a person's machine needs no mirror, keyring or pacman run, and the
bytes it gets are the ones this repository signed.

**One base for both cells.** MSYS2 publishes no ARM64 ``usr/``; on Windows 11 ARM the x86_64 base
runs emulated, and the ARM64 cell differs only in its toolchain (``clangarm64``).

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package

# The self-extracting base, which is what MSYS2 recommends for CI: Python's `tarfile` reads no zstd,
# and this needs nothing but Windows to unpack.
BASE = "https://repo.msys2.org/distrib/msys2-x86_64-latest.sfx.exe"

CELLS = {
    ("windows", "x86_64"): {
        "toolchain": ["base-devel", "mingw-w64-ucrt-x86_64-toolchain"],
        "compiler": "ucrt64/bin/gcc.exe",
    },
    ("windows", "aarch64"): {
        "toolchain": ["base-devel", "mingw-w64-clang-aarch64-toolchain"],
        "compiler": "clangarm64/bin/clang.exe",
    },
}


def version_of(day: str) -> str:
    """``2026-10-08`` -> ``2026.10.08``: the build date, so a newer build is the newer release."""
    return day.replace("-", ".")


def provides(target: tuple[str, str]) -> dict[str, str]:
    """What the smoke test runs. MixEngine puts none of it in ``bin/``: a toolchain has no clients."""
    compiler = CELLS[target]["compiler"]
    return {"bash": "usr/bin/bash.exe", Path(compiler).stem: compiler}


def bash(tree: Path, script: str, tolerate: bool = False) -> None:
    """Run *script* in the tree's own login shell, the way MSYS2 is initialised.

    *tolerate* is for the one command that can end its own shell: a core update replaces
    ``msys2-runtime`` underneath the ``bash`` running it, which then exits non-zero whatever the
    script says, so ``|| true`` inside the script cannot catch it.
    """
    environment = {
        "MSYSTEM": "MSYS",
        "CHERE_INVOKING": "1",
        "PATH": str(tree / "usr" / "bin"),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "TEMP": os.environ.get("TEMP", str(tree / "tmp")),
        "TMP": os.environ.get("TMP", str(tree / "tmp")),
    }
    print(f"msys2: {script}")
    subprocess.run([str(tree / "usr" / "bin" / "bash.exe"), "-lc", script],
                   check=not tolerate, timeout=3600, env=environment)


def build(tree: Path, target: tuple[str, str]) -> None:
    """Initialise the base, bring it up to date, and add the cell's toolchain."""
    bash(tree, "exit")  # the first login writes the keyring and /etc
    # A core update can end the first `-Syu` early by updating pacman or the runtime itself; the
    # second one finishes the job. MSYS2's own CI instructions run it twice for the same reason.
    bash(tree, "pacman -Syu --noconfirm", tolerate=True)
    bash(tree, "pacman -Syu --noconfirm")
    bash(tree, "pacman -S --needed --noconfirm " + " ".join(CELLS[target]["toolchain"]))
    bash(tree, "pacman -Scc --noconfirm")
    shutil.rmtree(tree / "var" / "cache" / "pacman" / "pkg", ignore_errors=True)


def smoke(tree: Path, target: tuple[str, str]) -> dict:
    """Compile and run one line of C from a directory the tree was moved to."""
    elsewhere = borrow.moved(tree)
    work = Path(tempfile.mkdtemp(prefix="msys2-smoke-"))
    try:
        compiler = elsewhere / CELLS[target]["compiler"]
        source, program = work / "hello.c", work / "hello.exe"
        source.write_text('#include <stdio.h>\nint main(void){puts("hello");return 0;}\n')
        environment = {
            "PATH": str(compiler.parent),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
            "TEMP": str(work),
            "TMP": str(work),
        }
        subprocess.run([str(compiler), str(source), "-o", str(program)],
                       check=True, env=environment, timeout=300)
        said = subprocess.run([str(program)], check=True, capture_output=True, text=True,
                              env=environment, timeout=60).stdout.strip()
        if said != "hello":
            raise SystemExit(f"the compiled program answered {said!r}")
        print(f"smoke: {compiler.name} built and ran C from {elsewhere}")
        return {"relocated": True, "ran": [f"{compiler.name} hello.c -> {said}"]}
    finally:
        borrow.discard(elsewhere)
        shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", default="latest",
        help="always 'latest': the version is the date of the build",
    )
    parser.add_argument("--out", default="dist", type=Path)
    args = parser.parse_args()
    if args.version != "latest":
        raise SystemExit(
            f"msys2 is versioned by its build date, so it can only be built as 'latest', "
            f"not {args.version!r}"
        )

    target = borrow.host("msys2")
    if target not in CELLS:
        borrow.unavailable(
            f"msys2 is a Windows toolchain; nothing to build for {target[0]}/{target[1]}"
        )

    version = version_of(datetime.date.today().isoformat())
    work = Path(tempfile.mkdtemp(prefix="mixengine-msys2-"))
    try:
        archive = work / "msys2-base.sfx.exe"
        print(f"fetching {BASE}")
        urllib.request.urlretrieve(BASE, archive)

        unpacked = work / "unpacked"
        unpacked.mkdir()
        # A 7-Zip self-extractor: `-y` answers yes, `-o` names where; the payload is `msys64/`.
        subprocess.run([str(archive), "-y", f"-o{unpacked}"], check=True, timeout=1800)
        tree = unpacked / "msys64"
        if not (tree / "usr" / "bin" / "bash.exe").is_file():
            raise SystemExit(
                f"the base unpacked without usr/bin/bash.exe: "
                f"{sorted(path.name for path in unpacked.iterdir())}"
            )

        build(tree, target)

        manifest = {
            "schema": 1,
            "kind": "msys2",
            "version": version,
            "os": target[0],
            "arch": target[1],
            "source": "built",
            "upstream": {
                "project": "msys2/msys2-installer",
                "url": BASE,
                "sha256": borrow.sha256(archive),
                "verified_against": (
                    "HTTPS to repo.msys2.org for the base; pacman verified every package it added "
                    "against MSYS2's own keyring"
                ),
            },
            "provides": provides(target),
        }
        manifest = borrow.declare(tree, manifest)
        manifest["smoke"] = smoke(tree, target)
        # "tar", as `ruby_unix.py` passes: `.tar.zst` where the runner's tar has zstd, `.tar.gz`
        # where it does not. MixEngine unpacks both on every system.
        borrow.publish(tree, manifest, args.out, "tar")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
