# MSYS2, the compiler Ruby on Windows does not ship

*Part of [mixengine-packages](../../README.md), which holds the table of what is packaged.*

Ruby for Windows is RubyInstaller's, borrowed and pruned ([ruby.md](ruby.md)), and it carries no
compiler. `gem install` of a gem with a C extension answers `MSYS2 could not be found` and exits 1,
which is the `native gems` entry of that artifact's `lacks`. Rails cannot be installed without one:
measured on 2026-10-08, `gem install rails` stops at `websocket-driver`, the first gem it pulls that
compiles C, and the `bundle install` inside `rails new` stops at `puma`, `bootsnap` and `nio4r`.

This package is the answer, as a package beside Ruby rather than a change to it. MixEngine installs it
into its home like any other package and points every Ruby at it through `MSYS2_PATH`, which is the
first place RubyInstaller looks for an MSYS2 (`ruby_installer/runtime/msys2_installation.rb`,
`iterate_msys_paths`). One install serves every Ruby version, and no Ruby directory is written to.

| OS / arch | Toolchain | How |
| --- | --- | --- |
| Windows x86_64 | `base-devel`, `mingw-w64-ucrt-x86_64-toolchain` (gcc) | **built** on `windows-2022` |
| Windows aarch64 | `base-devel`, `mingw-w64-clang-aarch64-toolchain` (clang) | **built** on `windows-11-arm` |
| macOS, Linux | — | a Ruby there compiles with the system's toolchain; nothing to package |

The two toolchains are the ones RubyInstaller's own `ridk install 3` adds, chosen per cell by the
same table RubyInstaller keeps (`ucrt64` for x64, `clangarm64` for ARM64).

## Built, not fetched on somebody's machine

The recipe, [`tools/msys2.py`](../../tools/msys2.py), starts from MSYS2's self-extracting base
(`msys2-x86_64-latest.sfx.exe`; Python's `tarfile` reads no zstd, and the extractor needs nothing
but Windows), logs in once to write the keyring, updates the base, installs the toolchain, empties
pacman's cache and packs the tree. A machine that installs it needs no MSYS2 mirror, no keyring and
no pacman run, and the bytes it gets are the ones this repository published.

**The first update ends its own shell, and the recipe expects it.** Updating `msys2-runtime`
replaces the DLL the running `bash` is using, which then exits 1 whatever the script asked for, so
`|| true` inside the script cannot catch it. The first `pacman -Syu` is therefore tolerated from the
outside and the second one is the one that has to succeed: the procedure MSYS2's own CI documents.

**One base for both cells.** MSYS2 publishes no ARM64 `usr/` at the time of writing. On Windows 11
ARM its x86_64 `bash`, `make` and `pacman` run under emulation, while everything the compiler
produces is native ARM64. The ARM64 cell differs only in its toolchain, and it is built and
smoke-tested on an ARM runner because an aarch64 clang cannot be run anywhere else.

## Versioned by date

There is no upstream version to follow: the base is "latest" and pacman brings it current. The
version is the build date, `YYYY.MM.DD`, so a newer build is the newer release in MixEngine's
lines-and-updates model, and `release/build.sh msys2 latest` is the only way to ask for one.

## What `provides` says, and what MixEngine does with it

`provides` names `bash` and the cell's compiler, because the index requires at least one entry and
those are what the smoke test ran. MixEngine adds **none** of them to `bin/`: package commands come
from a service recipe's clients, and MixEngine knows `msys2` as a *toolchain*, which it installs,
lists and removes but never runs.

## Measured

| | x86_64 | aarch64 |
| --- | --- | --- |
| Base downloaded | 43.1 MB (`.sfx.exe`) | the same base |
| Artifact | 300.3 MB as `.tar.zst` measured locally; published as `.zip` (see below) | 479.4 MB as `.tar.zst` on the first ARM run |
| Smoke test | `gcc.exe hello.c -> hello`, from a moved directory whose path holds a space | `clang.exe hello.c -> hello` |

**Published as a zip**, as every Windows cell in this repository is. The first CI run packed the
ARM64 tree with `tar --zstd` in 39 seconds and then watched the same command on `windows-2022` hang
for its whole thirty-minute timeout; `zipfile` depends on no program a runner image may or may not
carry.
