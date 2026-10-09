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

`provides` names `bash` and the cell's compiler as `cc`, because the index requires at least one
entry and those are what the smoke test ran. The compiler is `cc` on both cells, gcc on one and
clang on the other: `gather.py` refuses a version whose cells name different commands. MixEngine
adds **none** of them to `bin/`: package commands come from a service recipe's clients, and
MixEngine knows `msys2` as a *toolchain*, which it installs, lists and removes but never runs.

## What `keeps` says

The rule's second half throws out static and import libraries, because a runtime needs none of them.
A toolchain is the opposite case: the compiler links a gem's C extension against them. `keeps`
names each directory holding one (`ucrt64/lib` or `clangarm64/lib`, and `usr/lib`), read off the
tree when it is packed; the first publish was refused for the 1056 and 855 it had not declared.

## What a gem's MSYS2 packages bring

A gem that declares `msys2_mingw_dependencies` (Rails 8's `ruby-vips` asks for libvips) makes
RubyInstaller run `pacman -S --needed --noconfirm <package>` inside this tree. pacman installs the
package and its dependencies and **none of its optional dependencies**: libvips loads without its
heif, jxl and magick modules until `mingw-w64-ucrt-x86_64-libheif`, `-libjxl` and `-imagemagick` are
added with `usr/bin/pacman -S` from this package's directory.

The package database is the one of the build date, and measured on 2026-10-09 that costs nothing:
every file a 2026-10-08 database named still downloaded from `mirror.msys2.org` and
`repo.msys2.org`, which keeps superseded versions for a long time. A one-off 404 from one mirror is
pacman moving on to the next. Should a database ever be old enough for its files to be gone, the
answer is a newer `msys2` from `mix package available`, not `pacman -Sy` inside this one: a refreshed
database with the old packages installed is the partial upgrade MSYS2 does not support.

## Measured

| | x86_64 | aarch64 |
| --- | --- | --- |
| Base downloaded | 43.1 MB (`.sfx.exe`) | the same base |
| Artifact | 300.3 MB as `.tar.zst` measured locally; published as `.zip` (see below) | 479.4 MB as `.tar.zst` on the first ARM run |
| Smoke test (`cc`) | `gcc.exe hello.c -> hello`, from a moved directory whose path holds a space | `clang.exe hello.c -> hello` |

**Published as a zip**, as every Windows cell in this repository is. The first CI run packed the
ARM64 tree with `tar --zstd` in 39 seconds and then watched the same command on `windows-2022` hang
for its whole thirty-minute timeout; `zipfile` depends on no program a runner image may or may not
carry.
