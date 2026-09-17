#!/usr/bin/env python3
"""Compile Apache httpd on Windows, both architectures, with MSVC and upstream's own CMake builds.

**Every piece is built from source into one prefix**, in the order the next one needs it: zlib,
PCRE2, expat and nghttp2 with their CMake builds, OpenSSL with its own ``Configure`` and ``nmake``,
then APR, APR-util and httpd with theirs. httpd's CMake looks for APR, nghttp2 and PCRE under its own
install prefix by default, which is why everything shares one — the shape Apache Lounge's builds have.

**Libraries are DLLs here and static archives on Unix**, which is each platform's ordinary shape
rather than a difference in what the row means: the same pinned versions are compiled either way,
and on Windows a DLL beside ``httpd.exe`` is already the relocation — the loader searches the
application's directory first. **The C runtime is the dynamic one** (``/MD``): httpd, APR and every
module pass CRT-owned objects across DLL boundaries, and one CRT per DLL is the configuration that
invites that to break. The Visual C++ redistributable is therefore a declared precondition,
measured off the import tables rather than assumed.

**No assembler for OpenSSL** (``no-asm``): NASM is not on the ARM runner and the ARM64 assembler
path is a second toolchain to prove. It changes speed, not what the library does.

**One developer environment for everything.** ``vcvarsall.bat`` is run once and its environment
captured, so ``cl``, ``nmake`` and the Ninja that Visual Studio ships are the same toolchain for all
eight builds, and the native ARM64 compiler is the one selected on ``windows-11-arm``.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import httpd  # noqa: E402
import httpd_smoke  # noqa: E402
import mongodb  # noqa: E402

VSWHERE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
    / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"

# OpenSSL's `Configure` refuses an MSYS perl — the one first on `PATH` under `shell: bash` — because
# it writes POSIX paths into a makefile `nmake` reads. Both Windows runner images carry Strawberry.
PERL = Path(r"C:\Strawberry\perl\bin\perl.exe")

# `vcvarsall.bat` argument and OpenSSL target per architecture.
TARGETS = {
    "x86_64": {"vcvars": "x64", "openssl": "VC-WIN64A"},
    "aarch64": {"vcvars": "arm64", "openssl": "VC-WIN64-ARM"},
}

BUILD_TYPE = "Release"

POLICY = "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"


def developer_environment(arch: str) -> dict[str, str]:
    """The environment ``vcvarsall.bat`` sets up, captured so every later build runs inside it."""
    if not VSWHERE.is_file():
        raise SystemExit(f"no {VSWHERE}; this machine has no Visual Studio to build with")
    found = subprocess.run(
        [str(VSWHERE), "-latest", "-products", "*", "-property", "installationPath"],
        capture_output=True, text=True, timeout=300,
    ).stdout.strip().splitlines()
    if not found:
        raise SystemExit("vswhere names no Visual Studio installation")
    vcvars = Path(found[0]) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    if not vcvars.is_file():
        raise SystemExit(f"{vcvars} does not exist; the C++ workload is not installed")

    dumped = subprocess.run(
        f'"{vcvars}" {TARGETS[arch]["vcvars"]} >nul && set',
        shell=True, capture_output=True, text=True, timeout=600,
    )
    if dumped.returncode != 0:
        raise SystemExit(
            f"{vcvars} {TARGETS[arch]['vcvars']} exited {dumped.returncode}\n{dumped.stdout}"
        )
    environment = {}
    for line in dumped.stdout.splitlines():
        name, separator, value = line.partition("=")
        if separator and name:
            environment[name] = value

    if not PERL.is_file():
        raise SystemExit(f"no {PERL}; OpenSSL's Configure needs a native Windows perl")
    environment["PATH"] = f"{PERL.parent}{os.pathsep}{environment.get('PATH', '')}"
    for tool in ("cl", "nmake", "ninja", "cmake"):
        if not shutil.which(tool, path=environment["PATH"]):
            raise SystemExit(f"the developer environment has no {tool} on PATH")
    print(f"developer environment: {vcvars} {TARGETS[arch]['vcvars']}")
    return environment


def cmake(source_tree: Path, build: Path, prefix: Path, environment: dict[str, str],
          *options: str, configured: Callable[[Path], None] | None = None) -> None:
    """Configure, build and install one CMake project into *prefix* with Ninja.

    *configured* runs between the two, on the build directory — see :func:`rebase`, the one caller.
    """
    build.mkdir(parents=True, exist_ok=True)
    httpd.run(
        "cmake", "-G", "Ninja", "-S", source_tree, "-B", build,
        f"-DCMAKE_BUILD_TYPE={BUILD_TYPE}",
        f"-DCMAKE_INSTALL_PREFIX={prefix.as_posix()}",
        f"-DCMAKE_PREFIX_PATH={prefix.as_posix()}",
        *options,
        env=environment,
    )
    if configured is not None:
        configured(build)
    httpd.run("cmake", "--build", build, "--parallel", httpd.jobs(), env=environment)
    httpd.run("cmake", "--install", build, env=environment)


def rebase(build: Path) -> None:
    """Lift every preferred load address in the generated ``BaseAddr.ref`` above 4 GB, for ARM64.

    **The one thing on this row that ARM64 does not get for free.** httpd's Windows build keeps a
    central table of where each DLL would like to be loaded — ``os/win32/BaseAddr.ref``, addresses
    from ``0x6FF00000`` up — and passes it to the linker as ``/base:@<file>,<name>``. Every one of
    those is a 32-bit address, and ``link.exe`` refuses them outright for an ARM64 image:
    ``LNK1355: invalid base address 0x6FF00000; ARM64 image cannot have base address below 4GB``,
    measured on ``windows-11-arm`` at the first link of ``libhttpd.dll``.

    What is rewritten is the **copy CMake generated in the build directory**, not upstream's file,
    and 4 GB is added to each address so the table keeps the spacing its comment is about. A
    preferred base is a request: every image here is built with ASLR, so the loader picks the real
    address anyway, and what this buys is a link that succeeds rather than a different program.
    """
    table = build / "BaseAddr.ref"
    if not table.is_file():
        raise SystemExit(f"httpd's CMake build generated no {table}; its base address table moved")
    lifted = re.sub(
        r"(?m)^(\S+\.(?:dll|so)\s+)0x([0-9A-Fa-f]{8})\b",
        lambda row: f"{row.group(1)}0x{int(row.group(2), 16) + (1 << 32):09X}",
        table.read_text(encoding="utf-8"),
    )
    moved = len(re.findall(r"(?m)^\S+\.(?:dll|so)\s+0x1[0-9A-Fa-f]{8}\b", lifted))
    if not moved:
        raise SystemExit(f"{table} holds no 32-bit base address to lift; its shape changed")
    table.write_text(lifted, encoding="utf-8")
    print(f"lifted {moved} preferred load addresses above 4 GB, which ARM64 requires")


def openssl(source_tree: Path, prefix: Path, arch: str, environment: dict[str, str]) -> None:
    httpd.run(
        PERL, "Configure", TARGETS[arch]["openssl"], "no-asm", "no-tests", "no-docs",
        # No `--openssldir`: OpenSSL's Windows default is `C:\Program Files\Common Files\SSL`, which
        # only an administrator can write. A directory under the install prefix would be compiled in
        # as where `openssl.cnf` is read from, on a drive any user can create it on.
        f"--prefix={prefix}",
        cwd=source_tree, env=environment,
    )
    httpd.run("nmake", cwd=source_tree, env=environment, timeout=10800)
    httpd.run("nmake", "install_sw", cwd=source_tree, env=environment)

    # **`applink.c` only ships for the x86 and x64 targets**, and httpd's `support/ab.c` includes it
    # whenever OpenSSL was found — so the ARM64 build stops on `C1083: Cannot open include file:
    # 'openssl/applink.c'`, at `abs.exe`, after every module has already linked. The file is in the
    # source tree either way and is the same C on every architecture: it exports the callback that
    # lets OpenSSL use a file handle belonging to another CRT.
    installed = prefix / "include" / "openssl" / "applink.c"
    if not installed.is_file():
        shutil.copy2(source_tree / "ms" / "applink.c", installed)
        print(f"copied ms/applink.c to {installed}, which this OpenSSL target does not install")


def module_names(source_tree: Path) -> list[str]:
    """Every module httpd's CMake build knows, read out of its ``MODULE_LIST``."""
    text = (source_tree / "CMakeLists.txt").read_text(encoding="utf-8")
    names = sorted(set(re.findall(r'"modules/[\w/]+/mod_(\w+)\+[AIiaO]\+', text)))
    if not names:
        raise SystemExit("httpd's CMakeLists.txt lists no modules; its MODULE_LIST changed shape")
    unknown = sorted(set(httpd.MODULES) - set(names))
    if unknown:
        raise SystemExit(f"httpd's CMake build has no module {', '.join(unknown)}")
    return names


def build(version: str, source_tree: Path, unpacked: dict[str, Path], prefix: Path,
          arch: str, work: Path) -> list[str]:
    """Build every library and httpd into *prefix*. Answers httpd's CMake options, for the recipe."""
    environment = developer_environment(arch)
    builds = work / "build"

    cmake(unpacked["zlib"], builds / "zlib", prefix, environment,
          "-DZLIB_BUILD_TESTING=OFF", "-DZLIB_BUILD_STATIC=OFF")
    cmake(unpacked["pcre2"], builds / "pcre2", prefix, environment,
          "-DBUILD_SHARED_LIBS=ON", "-DBUILD_STATIC_LIBS=OFF", "-DPCRE2_BUILD_PCRE2GREP=OFF",
          "-DPCRE2_BUILD_TESTS=OFF", "-DPCRE2_SUPPORT_JIT=OFF", "-DPCRE2_SHOW_REPORT=OFF")
    cmake(unpacked["expat"], builds / "expat", prefix, environment,
          "-DEXPAT_SHARED_LIBS=ON", "-DEXPAT_BUILD_TOOLS=OFF", "-DEXPAT_BUILD_EXAMPLES=OFF",
          "-DEXPAT_BUILD_TESTS=OFF", "-DEXPAT_BUILD_DOCS=OFF", "-DEXPAT_BUILD_PKGCONFIG=OFF")
    cmake(unpacked["nghttp2"], builds / "nghttp2", prefix, environment,
          "-DENABLE_LIB_ONLY=ON", "-DBUILD_SHARED_LIBS=ON", "-DBUILD_STATIC_LIBS=OFF",
          "-DENABLE_DOC=OFF", "-DBUILD_TESTING=OFF")
    openssl(unpacked["openssl"], prefix, arch, environment)

    # APR and APR-util still declare a CMake minimum below 3.5, which CMake 4 — the one on the ARM
    # runner's `PATH` — refuses outright. This is CMake's own documented escape, a policy setting
    # rather than an edit to either project.
    cmake(unpacked["apr"], builds / "apr", prefix, environment, POLICY,
          "-DAPR_INSTALL_PRIVATE_H=ON", "-DAPR_BUILD_STATIC=OFF", "-DAPR_BUILD_TESTAPR=OFF",
          "-DINSTALL_PDB=OFF")

    expat = sorted((prefix / "lib").glob("libexpat*.lib"))
    if len(expat) != 1:
        raise SystemExit(f"expat installed {[path.name for path in expat]} into lib/, expected one")
    cmake(unpacked["apr-util"], builds / "apr-util", prefix, environment, POLICY,
          "-DAPU_HAVE_CRYPTO=OFF", "-DAPU_HAVE_ODBC=OFF", "-DAPR_HAS_LDAP=OFF",
          "-DAPR_BUILD_TESTAPR=OFF", "-DINSTALL_PDB=OFF",
          f"-DEXPAT_INCLUDE_DIR={(prefix / 'include').as_posix()}",
          f"-DEXPAT_LIBRARY={expat[0].as_posix()}")

    wanted = set(httpd.MODULES)
    options = [
        "-DINSTALL_PDB=OFF", "-DINSTALL_MANUAL=OFF",
        f"-DOPENSSL_ROOT_DIR={prefix.as_posix()}",
        # Upper case, so a module whose prerequisite was not found stops the configure rather than
        # being skipped with a status line nobody reads.
        *(f"-DENABLE_{name.upper()}={'A' if name in wanted else 'O'}"
          for name in module_names(source_tree)),
    ]
    cmake(source_tree, builds / "httpd", prefix, environment, *options,
          configured=rebase if arch == "aarch64" else None)
    return options


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="'2.4', an exact version, or 'latest'")
    parser.add_argument("--out", default=Path("dist"), type=Path)
    arguments = parser.parse_args()

    operating_system, arch = borrow.host("httpd")
    if operating_system != "windows":
        raise SystemExit("this is the Windows recipe; use tools/httpd.py")

    work = Path(tempfile.mkdtemp(prefix="mixengine-httpd-"))
    version, source_tree, digest, url = httpd.source(arguments.version, work)
    unpacked = httpd.libraries(work)
    print(f"packing httpd {version} for {operating_system}/{arch}")
    prefix = Path("C:/mixengine") / f"httpd-{version}"
    if prefix.exists():
        shutil.rmtree(prefix)
    prefix.mkdir(parents=True)

    options = build(version, source_tree, unpacked, prefix, arch, work)
    tree = httpd.assemble(prefix, work, windows=True)
    httpd.check_modules(tree)
    httpd.collect_licences(tree, source_tree, unpacked)

    enabled = [option for option in options if option.endswith("=A")]
    manifest = httpd.describe(
        version, (operating_system, arch), url, digest,
        f"httpd-{version}.tar.gz from source (sha512 verified against the ASF's .sha512); MSVC "
        f"{TARGETS[arch]['vcvars']}, /MD, CMake {' '.join(enabled)}; {httpd.pinned()} built as DLLs, "
        f"OpenSSL {TARGETS[arch]['openssl']} no-asm",
    )
    needed = mongodb.vcredist(tree)
    if needed:
        manifest["requires"] = {"vcredist": needed}
        print(f"needs the Visual C++ {needed} redistributable")

    manifest["smoke"] = httpd_smoke.smoke(tree, version, manifest)
    borrow.publish(tree, manifest, arguments.out, "zip")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
