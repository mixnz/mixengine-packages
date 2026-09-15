# MongoDB, and the shell that is no longer inside it

*Design for [P18 and P18a](../../roadmap.md). What this settles is the packaging half: which lines
are offered, which cell comes from where, what the rule takes out, and what the finished artifact
promises a daemon. What runs `mongod` — a rendered `mongod.conf`, a data directory made once, a port,
a health check — is MixEngine's side and is not decided here, but the contract it will be written
against is.*

---

## Why this row exists at all

MixEngine already requires the PHP `mongodb` extension on **every branch it ships**, 7.0 through the
newest, on all six cells — [P2](../../roadmap-history.md) is the task that failed a Windows build
over its absence, and `php_legacy_unix.py` still says *"MixEngine offers {package} on every version
it ships, so an artifact without it is not one worth publishing"*. MixDB connects to MongoDB and
fetches `mongodump` and `mongorestore` to do it.

So the index makes every PHP able to talk to a MongoDB, the desktop client can browse one, and
nothing here can install one. That is the gap, and it is the whole argument: this is not a kind
being added because it is popular, it is the missing half of a promise the index already makes.

What the row does **not** have behind it is blueprint demand. None of the eleven blueprints in
MixEngine's gallery uses MongoDB, and this document does not pretend otherwise.

## What is offered

Five lines, floor at **6.0**, every cell borrowed:

| Version | macOS aarch64 | macOS x86_64 | Linux x86_64 | Linux aarch64 | Windows x86_64 | Windows aarch64 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **6.0** | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **7.0** | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **8.0** | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **8.2** | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **8.3** | ✅ | ✅ | ✅ | ✅ | ✅ | — |

**Which lines those are is read off upstream's catalogue rather than written down here.**
`downloads.mongodb.org/full.json` flags every release `production_release` and `lts_release`, and
the pair selects exactly the five above; the rapid releases between them (8.1, 7.3, 7.2, 7.1, 6.3 …)
carry `continuous_release` and are not offered. A `9.0.0-rc0` is already in that document, dated
2026-07-14, which is what the index's `rc` channel is for whenever it is wanted.

**Windows on ARM is upstream's empty cell, not this repository's.** No version of MongoDB has ever
published an `aarch64` Windows build — not a rapid release, not an LTS, not back to 4.4.

**The floor is 6.0 because that is where macOS stops being whole.** Upstream withdrew macOS from two
lines while they were still being patched: `4.4.29` and `5.0.31` offer a `macos-x86_64` tarball and
`4.4.31` and `5.0.34` offer no macOS asset of any kind. macOS **arm64** starts at 6.0. Filling 5.0
or 4.4 would mean compiling MongoDB on macOS for a line upstream has abandoned there — the MySQL
5.6/5.7 shape, at a much higher price, for a database nobody has asked for at that version.

## Where each cell comes from, and what it needs

Borrowed from `fastdl.mongodb.org`, resolved through `full.json`, which carries a SHA-256 per
archive — the same shape `mariadb.py` and `postgres.py` already use, so `upstream.sha256` is checked
against the publisher's own document rather than against a hash computed here and then trusted.

**Linux is a choice between two bad names and one good rule.** Upstream builds per distribution, and
the two candidates differ in what they expect the machine to have. Measured on 8.3.11, x86_64:

| Build | Highest glibc symbol referenced | Expects from the system |
| --- | --- | --- |
| `rhel8` (unpacks as `rhel88`) | 2.25 | `libssl.so.1.1`, `libcrypto.so.1.1`, `libcurl.so.4` |
| `rhel93` | 2.34 | `libssl.so.3`, `libcrypto.so.3`, `libcurl.so.4` |

The lower floor is the one that needs **OpenSSL 1.1.1, which upstream stopped patching in September
2023**. Shipping an artifact whose TLS library is three years past its end is not a trade this
repository makes for two glibc versions, and 2.34 is below the 2.35 the MariaDB Linux cells already
impose.

So the rule is written as a criterion, not as a name: **the build with the lowest glibc floor among
those that link OpenSSL 3**, and the recipe reads `DT_NEEDED` out of the finished `mongod` to prove
which one it got rather than inferring it from the file name. As of today that is expected to
resolve to `rhel93` for 8.x and `rhel90` for 6.0 and 7.0 — `rhel93` has no `aarch64` build below
8.2, which is exactly the kind of per-line difference a name hard-coded in the recipe would have
shipped as a 404. Only `rhel93` and `rhel8` have actually been read; that RHEL 9.0 links OpenSSL 3
is what its distribution ships, and it is on the list below to be measured rather than assumed.

Both binaries already carry `RUNPATH=$ORIGIN/../lib`, so `relocate.bundle` — written for
`mariadb_deb.py`, which had the same problem with `libssl.so.3` — copies the three libraries into
`lib/` and rewrites nothing. The glibc floor of the finished artifact is the highest floor of
anything in it, including what is bundled, and it is measured rather than claimed.

**macOS** takes the `base` tarballs, both architectures, native on each.

**Windows** takes the `base` zip.

## What the rule takes out

*One version means one thing, and no more than is needed* does more work on this row than on any
row since MariaDB's, because upstream's Windows zip is almost entirely not a database. Measured on
`mongodb-windows-x86_64-8.3.11.zip`, 923.3 MB over twelve entries, read out of the zip's own central
directory:

| Entry | Compressed | Kept? |
| --- | ---: | --- |
| `bin/mongod.pdb` | 493.1 MB | no — debug symbols, which is [P6b](../../roadmap-history.md) |
| `bin/mongos.pdb` | 350.5 MB | no — same |
| `bin/mongod.exe` | 32.5 MB | yes |
| `bin/mongos.exe` | 21.8 MB | yes |
| `bin/vc_redist.x64.exe` | 25.4 MB | no — an installer is not something a running process reads |
| `bin/Install-Compass.ps1` | ~0 | no — a downloader for a different product |
| four licence documents | ~0 | yes |

**843.6 MB of the archive is debug symbols and 25.4 MB is a redistributable installer**; what is
left is about 54 MB. The `vc_redist.x64.exe` is not merely dropped — the precondition it was there
to satisfy becomes `requires.vcredist`, measured off `mongod.exe`'s import table the way MySQL's
`msvcr100.dll` was, so a machine that cannot run it is told rather than shown a loader error.

**The Unix tarballs are clean by comparison and still carry what a strip removes.** Each holds
`bin/mongod`, `bin/mongos`, `bin/install_compass` and four licence files — nothing else. Upstream
publishes DWARF in a separate `debugsymbols` tarball, so there is none inside these; what is inside
is the symbol table, and on `mongod` alone `.symtab` and `.strtab` are **45.6 MB** of a 169.5 MB
binary. `strip.py` already does this operation and proves it structurally — the loader's view of the
file is identical across it — so no new machinery is needed, and the result is declared in
`upstream.changed` with the command that made it.

`bin/install_compass` goes for the reason its Windows twin goes, which also keeps the five cells
saying the same thing: after packing, every cell contains `mongod`, `mongos` and the licences, and
differs only by the `lib/` the two Linux cells need.

## What the artifact promises

The contract, so that MixEngine's side can be written against it without re-negotiating anything:

```
kind        "mongodb"
provides    { "mongod": "bin/mongod[.exe]", "mongos": "bin/mongos[.exe]" }
source      "borrowed"
upstream    { url, sha256 (both from full.json), project: "mongodb/mongo",
              release: <the release's public_githash> }
requires    glibc     Linux, measured from .gnu.version_r
            macos     measured from LC_BUILD_VERSION
            vcredist  Windows, measured from mongod.exe's imports
            cpu       "avx", on every cell — see below
smoke       { relocated: true, ran: [...] }
```

Three things that contract says out loud, because each is something a client would otherwise
discover at run time:

- **The archive keeps upstream's layout.** `bin/` on every cell; `lib/` exists on the two Linux
  cells and nowhere else, and it holds bundled libraries rather than anything a user calls.
- **There is no shell in it.** From 6.0 the server tarball ships no `mongo` and no `mongosh`, so
  `mix database open` has to reach for the `mongosh` kind below. A daemon that assumes a database
  package contains its own client is wrong about this one.
- **`mongod` needs a data directory that exists before it starts**, made once, which puts it in the
  same group as MariaDB and PostgreSQL rather than with Redis.

## The one schema change

`index.schema.json` gains an optional `requires.cpu`, whose value is `"avx"`.

MongoDB 5.0 and everything after it **refuse to start on an x86_64 CPU without AVX** — Intel before
Sandy Bridge, AMD before Bulldozer. Every version offered here is past that line. `requires` today
can say which C runtime, which macOS, which glibc and what to do about tzdata, and cannot say this;
an artifact that cannot state its own precondition hands the user a process that dies instead of a
sentence that explains.

The schema says a bumped `schema` is for *"a change a current client cannot read. Adding an optional
field is not one."* So `schema` stays at `1`. `artifact.schema.json` needs nothing: `requires` there
is already an open object.

## `mongosh`, as its own kind

Apache-2.0, published from `mongodb-js/mongosh`, versioned on its own clock — `2.11.1` at the time
of writing, released the same day as this document. Five cells, the same five: `darwin-arm64`,
`darwin-x64`, `linux-arm64`, `linux-x64`, `win32-x64`, and no Windows on ARM.

Each archive is 60–95 MB because a Node.js runtime is inside it. Linux is published three ways —
one archive per system OpenSSL, plus one that carries its own. **The self-contained one is what is
taken**, which costs about 4 MB against the `openssl3` variant and buys an artifact with nothing to
bundle and no opinion about the machine's OpenSSL.

```
kind      "mongosh"
provides  { "mongosh": "bin/mongosh[.exe]" }
```

It is a second kind rather than a second directory in the server archive because they are two
products: two release schedules, two licences, and a shell version that pairs with several server
versions. One archive holding both would make *one version means one thing* unanswerable — whose
version would it be?

## Licence, and the source that has to remain reachable

**MongoDB Community Server is SSPL v1** — every release after 16 October 2018, which is every
release offered here. There is no AGPL option: only versions from before that date are AGPL, and
none of them are packaged.

SSPL permits what this repository does. Its obligations bite on *offering the program as a service*,
which nothing here does, and it is otherwise a copyleft in GPLv3's shape — which means the
corresponding source has to stay reachable for what is conveyed. The route is
[Redis's](../../packages/redis-memcached.md), which spans the same kind of licence: nothing is
patched, so the manifest naming exactly what was taken is the whole of the claim. For MongoDB the
naming is unusually strong, because `full.json` publishes `public_githash` per release and
`github.com/mongodb/mongo` carries the matching `r<version>` tag — a reader can go from the archive
to the commit it was built from without trusting a sentence in a document.

**No source tarball is mirrored into this repository's releases.** That was weighed: it would make
the source promise as durable as the artifact promise, at a cost of roughly a hundred megabytes per
version, and it is not what the Redis row does. If the reasoning ever changes it changes for both
rows at once.

`mongosh` is Apache-2.0 and asks for none of this.

## No end-of-life dates, on purpose

MongoDB publishes its lifecycle as an HTML table and nothing else — no JSON, no API, no feed that
`eol.py --check` could prove a transcription against. `data/eol.json` holds six kinds because six
publishers offer a machine-readable document, and a seventh entry transcribed by hand from a web
page is the precise thing [P10](../../roadmap-history.md) was written to stop.

So `mongodb` and `mongosh` join `mysql`, `redis`, `memcached`, `nginx` and `caddy`: no `eol` field
in the index. `eol.py`'s docstring, which currently says "six kinds, six publishers", has to say that
this absence is a decision rather than an omission.

## How it is proven

`tools/mongodb_smoke.py`, in the shape `postgres_smoke.py` and `mysql_smoke.py` already have:
*run, configure, health-check, stop* rather than `--version`. Concretely — unpack, move the tree
somewhere unrelated, make a data directory, start `mongod` on a free port, ask it a question it
answers before authentication is configured, then shut down and confirm the process is gone.

**The question is asked over the wire, not through `mongosh`.** That is the one place this document
changed its mind while the plan was being written, and the reason is the second kind existing at
all: `mongosh` is a different package on a different release clock, so a server smoke test that
needs it is a test that can go red for a reason that has nothing to do with the artifact under test
— and on the day `mongosh` has no build for a cell, the server for that cell would become
unprovable. What is sent instead is an `OP_MSG` carrying `{hello: 1}`, which is the first thing
every driver sends, in about forty lines of `struct` and a socket.

One thing to check before the recipe is written rather than after: **whether a GitHub Windows
runner's administrator token changes how `mongod` behaves.**
[P12a](../../roadmap-history.md) is PostgreSQL refusing to be smoke-tested under exactly that
condition, and it cost two red workflows to find out.

## What this does not do

- **No macOS build for 5.0 or 4.4.** Stated as a floor, not attempted.
- **No database tools.** `mongodump`, `mongorestore` and the rest are a third release train, and
  MixDB already fetches them from `downloads.mongodb.org/tools/db/release.json` on its own.
- **No Enterprise edition, no `mongo_crypt_shared`, no `cryptd`.** Different licence, different
  archive, and nothing a local development environment reaches for.
- **No debug symbols**, published or kept.
- **Nothing in MixEngine.** The service recipe, its `mongod.conf`, the first-run ritual, the port
  allocation and the CLI's view of it are that repository's work, against the contract above.

## What is left to measure before a line of the recipe is written

Everything above that is a number was measured; these are the numbers that are not there yet.

1. The macOS floor, from `LC_BUILD_VERSION` in `mongod` on both architectures and every offered line.
2. The Windows redistributable, from `mongod.exe`'s import table — `vc_redist.x64.exe` being present
   in the zip is a hint, not a version.
3. `DT_NEEDED` and the glibc floor of every Linux build actually taken — both architectures, all
   five lines. Two x86_64 builds of 8.3.11 have been read and nothing else; `rhel90`, which is what
   6.0 and 7.0 are expected to resolve to, has not.
4. Whether anything in the two Linux cells reaches outside its own tree after `relocate.bundle` —
   which is what `relocate.verify` answers, and what decides whether the bundling is finished.

## The two tasks

- **P18 — MongoDB**: `tools/mongodb.py`, `tools/mongodb_smoke.py`,
  `.github/workflows/build-mongodb.yml`, the `requires.cpu` field, `docs/packages/mongodb.md`, and a
  row in the README table.
- **P18a — `mongosh`**: `tools/mongosh.py` and `.github/workflows/build-mongosh.yml`, on the same
  page, because its only reason to exist is P18.

Nothing in either touches `mkindex.py`, `parity.py`, `permanence.py`, `borrow.py`, `strip.py` or
`relocate.py`. Every one of those is already kind-agnostic, which is why a new kind here is two
recipes and a workflow rather than a change to the pipeline.
