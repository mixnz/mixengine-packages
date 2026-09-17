# Valkey

*Part of [mixengine-packages](../../README.md), which holds the table of what is packaged.*

The Redis row's BSD continuation, built from source the way Redis is:

| OS / arch | Range | How |
| --- | --- | --- |
| macOS aarch64, x86_64 | **7.2 – newest** | **built** from upstream's tarball |
| Linux x86_64, aarch64 | **7.2 – newest** | **built**, on Ubuntu 22.04 for the glibc floor |
| Windows x86_64 | **8.0 – newest** | **built** against Cygwin, `cygwin1.dll` beside the binaries |
| Windows aarch64 | — | there is no Cygwin for ARM64 |

The design, and what was measured before the recipe was written, is
[the spec](../superpowers/specs/2026-09-17-valkey-packaging-design.md).

## Why it is a row

The Redis row's floor is 7.2 because 7.2 is the last BSD-3 Redis: 7.4 is RSALv2/SSPLv1 and 8.0 adds
AGPLv3. Valkey forked from Redis 7.2.4 in March 2024 and is **BSD-3-Clause on every line**, speaks the
same protocol, and takes the same clients. So it is where a user who needs a permissive in-memory store
past 7.2 goes — and it is its own kind, because P8 was right that a Windows cell of `redis` holding
Valkey would make one version mean two programs.

## The build is Redis's, and so is the code

`tools/valkey.py` imports from `tools/redis.py` everything that is about Cygwin and `make`: finding
Cygwin and proving it is Cygwin rather than Git for Windows' MSYS2, running a script under it with its
own tools on `PATH`, reading `DEPENDENCY_TARGETS` out of the tarball being built, and the two compiler
flags Cygwin's headers need. What is Valkey's is the names, the licence table and the smoke test. One
runtime's quirks live in one file.

Core only, with upstream's defaults of no TLS and no RDMA — the Redis row's choices for its reasons.
`valkey-benchmark` and `valkey-sentinel` are removed after install, as Redis's are. The versions and
their digests come from `valkey-io/valkey-hashes`, in `redis-hashes`' exact format; release candidates
are in that file and are not offered.

**No `redis-*` names.** Every line's `src/Makefile` says `USE_REDIS_SYMLINKS?=yes`, which makes
`install` add `redis-server`, `redis-cli` and the rest as links to Valkey's binaries — names that would
collide with the `redis` kind on a `PATH`. The build passes `USE_REDIS_SYMLINKS=no`, and the recipe
refuses a tree in which any `redis-*` name survived.

## Windows, and the line it starts at

**7.2 has no Windows cell, for Redis 7.2's reason.** It compiles under Cygwin, links and bundles
`cygwin1.dll`, and then `valkey-server --version` exits 2816 — `0xB00`, a process killed by SIGSEGV —
which is what Redis 7.2.15 does on the same runner, traced there to an access violation between
`time()` and the version banner. Valkey 7.2 is that code. 8.0, 8.1, 9.0 and 9.1 built and passed the
whole smoke test under Cygwin in the same hour, so `WINDOWS_FLOOR` is 8.0, and nothing is patched and
no line is compiled with different flags to move it.

The Windows cells carry `cygwin1.dll` and, from 8.0, `cyggcc_s-seh-1.dll` beside the binaries, both
found by reading the import tables and shipped with their licences.

## Licences

Valkey's `COPYING`, and the licence of everything compiled into it, which changes on every line:
`hiredis` becomes `libvalkey` at 9.0, `fast_float` arrives at 8.1 with its MIT text in the header
comment of `fast_float.h` and, from 9.1, of `ffc.h`. Two `deps/` directories are named as not
redistributed rather than skipped by pattern — `fast_float_c_interface`, one `.cpp` of Valkey's own
built only with `USE_FAST_FLOAT=yes`, and `gtest-parallel`, a test runner — so a genuinely new directory
still stops the build.

## What is proven

From a directory the tree was moved to: `valkey-server --version` names the release; the server starts
against a rendered `valkey.conf` with a quoted `dir` and answers `PING`; `INFO server` reports this
archive's `valkey_version` — not `redis_version`, which every line also reports for clients and which
says 7.2.4 on the 7.2 line; a key is written and read back; `EVAL` runs a Lua script, because from 9.1
the Lua engine is a module linked into the server rather than part of it; and `SHUTDOWN NOSAVE` stops
it.

**No end-of-life dates.** Valkey's download page lists the newest release of each major and states no
policy or date.
