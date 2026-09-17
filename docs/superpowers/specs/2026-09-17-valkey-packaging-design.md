# Valkey, the Redis row's BSD continuation

*Design for a proposed **P21**. It settles whether Valkey is a kind, which lines it offers, how each
cell is made, and what the artifact promises. It does not change the Redis row.*

---

## Why this row exists at all

[P8](../../roadmap-history.md) set the Redis floor at 7.2, and part of the reason was a licence:
**7.2 is the last BSD-3 Redis**. 7.4 is RSALv2/SSPLv1, and 8.0 adds AGPLv3 as a third option. The
index offers all of them, and it says which is which; what it does not offer is a way forward for
somebody who needs an in-memory store that stays under a permissive licence past 7.2.

Valkey is that way forward. It forked from Redis 7.2.4 in March 2024, it is **BSD-3-Clause on every
line** (`api.github.com/repos/valkey-io/valkey/license` answers `BSD-3-Clause`), it speaks the same
protocol, and a Redis client connects to it unchanged.

**Valkey has been asked before, and it was a different question.** P8 and P8a considered it only as a
way to fill Redis's *Windows* cell, and it was rightly refused: a fork of the same POSIX program does
not make a Windows build easier, and a Windows cell of `redis` holding Valkey would make a version
mean two things. Asked as its **own kind**, none of those reasons apply.

## What is offered

Five lines, every cell built here:

| Version | macOS aarch64 | macOS x86_64 | Linux x86_64 | Linux aarch64 | Windows x86_64 | Windows aarch64 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **7.2** | ✅ | ✅ | ✅ | ✅ | ? | — |
| **8.0** | ✅ | ✅ | ✅ | ✅ | ? | — |
| **8.1** | ✅ | ✅ | ✅ | ✅ | ? | — |
| **9.0** | ✅ | ✅ | ✅ | ✅ | ? | — |
| **9.1** | ✅ | ✅ | ✅ | ✅ | ? | — |

**The lines are read off upstream, not listed here.** `valkey-io/valkey-hashes` is upstream's own
catalogue, one line per tarball, in **exactly `redis-hashes`' format** —
`hash valkey-9.1.2.tar.gz sha256 19c23908… https://github.com/valkey-io/valkey/archive/refs/tags/9.1.2.tar.gz`
— so the resolver `redis.py` already has reads it with a different prefix. On 2026-09-17 it lists
stable releases on 7.2 (newest 7.2.14), 8.0 (8.0.11), 8.1 (8.1.10), 9.0 (9.0.6) and 9.1 (9.1.2), plus
`9.2.0-rc1`. All five stable lines were patched on 2026-07-21, and every line but 7.2 again between 2026-08-31
and 2026-09-01.

**Windows on ARM is empty for Redis's reason**: there is no Cygwin for aarch64, and an aarch64 archive
may not hold x86_64 binaries.

**Windows x86_64 is a question mark, and it is the one thing in this document that can only be
answered on a runner.** See below.

## Where each cell comes from

**Built everywhere, including where a borrow looks possible.** Upstream publishes binaries at
`download.valkey.io/releases/valkey-<version>-<jammy|noble>-<arm64|x86_64>.tar.gz`, with a `.sha256`
beside each — for Ubuntu only, and nothing for macOS or Windows. Borrowing the two Linux cells would
still leave the macOS cells to compile, which is **three routes to one version** again: two Ubuntu
builds linked against their distribution's libraries, and two macOS builds made here. Redis's row
builds all four Unix cells from one recipe for exactly this reason, and this row follows it.

The build is `redis.py`'s, with the names changed: `make -C src all`, core only, no TLS, no RDMA, no
bundled modules. Each of those choices is Redis's for Redis's reasons — no TLS because a loopback
connection on a developer's machine is not worth a library to bundle and a floor to keep current —
and each is repeated here so the two rows answer the same questions the same way.

**The source is reached through `valkey-hashes` and checked against it**, so the digest and the version
come from one publisher document, as with Redis.

## Windows, which is the part that has to be tried

Redis's Windows cell is the same source compiled under Cygwin with nothing patched, and 7.2 is the one
Redis line that compiles there and then faults in its own startup — an access violation between
`time()` and the version banner, recorded in [P12b](../../roadmap-history.md). **Valkey 7.2 forked from
that exact code**, so the expectation is that Valkey 7.2 does the same, and that Valkey's Windows floor
starts one line higher, at 8.0 — the shape Redis's already has.

Beyond 7.2, Valkey is no longer Redis: 8.0 rewrote I/O threading and 8.1 replaced the main hash table.
Neither was written with Cygwin in mind, and nobody upstream builds there. So the plan is to run the
Cygwin leg on every line and let each line's result be its answer:

- a line that compiles unpatched and passes the smoke test ships a Windows cell;
- a line that does not is an empty cell with the failure written down in the recipe, as `WINDOWS_FLOOR`
  is in `redis.py`;
- **nothing is patched to make it compile** — the rule Redis's row already holds.

## What the artifact promises

```
kind        "valkey"
provides    { "valkey-server":    "bin/valkey-server[.exe]",
              "valkey-cli":       "bin/valkey-cli[.exe]",
              "valkey-check-rdb": "bin/valkey-check-rdb[.exe]",
              "valkey-check-aof": "bin/valkey-check-aof[.exe]" }
source      "built"
upstream    { url, sha256 (from valkey-hashes), project: "valkey-io/valkey" }
requires    glibc   Linux, measured
            macos   measured
smoke       { relocated: true, ran: [...] }
```

- **The same four names the Redis row provides**, in Valkey's spelling — the server, the client, and
  the two check tools, which upstream installs as copies of the server that choose their behaviour by
  `argv[0]`. Four rather than the two first written here, so the two rows can be told apart by name
  alone and otherwise answer the same way; `valkey-benchmark` and `valkey-sentinel` go for Redis's
  reasons.
- **No `redis-*` names.** Every line's `src/Makefile` says `USE_REDIS_SYMLINKS?=yes`, which makes
  `make install` add `redis-server`, `redis-cli` and the rest as symlinks to the Valkey binaries. They
  are a second name for a program the archive already provides, a Cygwin symlink is one only Cygwin
  resolves (`redis.py` already refuses them for that reason), and an archive answering `redis-server`
  would collide with the `redis` kind on a `PATH`. So the build passes `USE_REDIS_SYMLINKS=no`, which
  upstream offers by name on all five lines, and the archive holds only the `valkey-*` names.
- **`valkey-server` takes its whole configuration from `argv`** and resolves nothing relative to where
  it was built, as Redis does; `relocate.verify` is what proves it.
- **Nothing on Windows but `cygwin1.dll`**, LGPLv3, beside the binaries, with its licence — for the
  lines that have a Windows cell at all.

## Licence

BSD-3-Clause on every line, plus the licences of what Valkey vendors in `deps/`, which travel as
Redis's do, and LGPLv3 for `cygwin1.dll` on Windows. Nothing here asks for the source-availability
work the Redis 7.4+ lines need.

**What `deps/` holds is not the same on any two lines**, measured on the newest tarball of each:

| Line | `deps/` | `DEPENDENCY_TARGETS` |
| --- | --- | --- |
| 7.2, 8.0 | fpconv, hdr_histogram, hiredis, jemalloc, linenoise, lua | hiredis linenoise lua hdr_histogram fpconv |
| 8.1 | + fast_float, fast_float_c_interface | the same |
| 9.0 | hiredis → **libvalkey** | libvalkey linenoise lua hdr_histogram fpconv |
| 9.1 | − fast_float_c_interface, + gtest-parallel | libvalkey linenoise hdr_histogram fpconv |

So the licence table is Redis's shape with three differences. `libvalkey` carries `COPYING`.
`fast_float` has no licence file: the MIT text is the header comment of `fast_float.h` on 8.1 and 9.0
and of `ffc.h` on 9.1, so either file is accepted. And two directories are not redistributed code with
a licence of their own: `fast_float_c_interface` is one `.cpp` of Valkey's, compiled only with
`USE_FAST_FLOAT=yes`, which is off by default and covered by `COPYING` when it is not; and
`gtest-parallel` is a test runner, compiled into nothing. Both are named as such, so a genuinely new
directory still stops the build.

**Lua left `DEPENDENCY_TARGETS` on 9.1 and did not leave the server.** From 9.1 the scripting engine is
a module, built by default as a *static* one — `modules/lua/libvalkeylua.a` linked into
`valkey-server` with `deps/lua` — so the binary still runs `EVAL` and still redistributes Lua. The smoke
test runs a script for that reason.

## No end-of-life dates, on purpose

`valkey.io/download/` lists the newest release of each major and states no maintenance policy or end
date. Nothing machine-readable exists, so `valkey` has no `eol` field.

## How it is proven

The Redis smoke shape: move the tree, start `valkey-server` against a rendered configuration on a free
port with no persistence, `PING`, `INFO server` whose `valkey_version` matches the manifest, `SET` and
`GET`, an `EVAL` that proves the Lua engine is in the binary, then `SHUTDOWN NOSAVE` and confirm the
process is gone. `INFO` is read for `valkey_version` specifically: every line also reports a
`redis_version` for client compatibility — 7.2.4 on the 7.2 line — which is not this archive's version.

## What this does not do

- **No change to the `redis` kind**, and no statement that Valkey replaces it.
- **No `valkey-bundle` modules** (JSON, Bloom, Search, LDAP) — separate repositories and separate
  builds, which is Redis's modules decision again.
- **No TLS, no RDMA.**
- **Nothing in MixEngine**: whether a blueprint that asks for "redis" may be given Valkey is a
  question for that repository, and this document deliberately does not answer it.

## What is left to measure before a line of the recipe is written

1. **Decided while reading `redis.py`:** the parts that are about Cygwin and `make` — finding and
   running Cygwin, reading `DEPENDENCY_TARGETS`, the two `CFLAGS`, a free port — are imported from
   `redis.py`; the parts that are about the program — names, licences, the smoke test — are Valkey's
   own in `tools/valkey.py`. A second copy of the Cygwin workarounds would be two places for one
   runtime's quirks to drift.
2. The Cygwin leg on all five lines, as above. No Cygwin on the development machine, so CI answers.
3. The macOS floor and the glibc floor of each Unix cell.
4. `9.2.0-rc1` is in the catalogue: **not offered** — the recipe takes three-part versions only, as
   Redis's does.

## The task

**P21 — Valkey**: `tools/valkey.py`, `.github/workflows/build-valkey.yml`, a section on
`docs/packages/redis-memcached.md` (or a page of its own if the Windows story diverges), a row in the
README table, and the absence in `eol.py`'s docstring.
