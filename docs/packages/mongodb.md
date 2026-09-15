# MongoDB, and the half of a promise the index already made

*Part of [mixengine-packages](../../README.md), which holds the table of what is packaged.*

Every PHP this repository publishes carries the `mongodb` extension, on every branch and every cell,
because [P2](../roadmap-history.md) fails a build without it — `php_legacy_unix.py` says so in as
many words: *"MixEngine offers {package} on every version it ships, so an artifact without it is not
one worth publishing"*. MixDB connects to MongoDB and fetches `mongodump` to do it. And until this
row, nothing here installed a MongoDB for any of that to talk to.

That is what this row is for. It is not a kind added because it is popular — no blueprint in
MixEngine's gallery uses MongoDB — it is the missing half of a promise the index was already making.

| OS / arch | Range | How |
| --- | --- | --- |
| Windows x86_64 | **6.0 – newest** | **borrowed** — the official `mongodb-windows-x86_64-<version>.zip`, minus 91% of it |
| Windows aarch64 | — | upstream has never built one, at any version |
| macOS aarch64, x86_64 | **6.0 – newest** | **borrowed** — the official `mongodb-macos-<arch>` tarballs |
| Linux x86_64, aarch64 | **6.0 – newest** | **borrowed** — whichever per-distribution build the recipe measures, see below |

Five lines: 6.0, 7.0, 8.0, 8.2 and 8.3. `mongod` and `mongos`, and nothing else — **there is no
shell in these archives**, which is the subject of the last section.

## Why the floor is 6.0, and why it is a constant rather than a query

Upstream's catalogue flags each release `production_release` and `lts_release`, and the design this
row was written from assumed that pair selected exactly the five lines above. It does not. Measured
against `downloads.mongodb.org`, it selects **seven**: MongoDB calls 5.0 and 4.4 LTS as well, and
goes on publishing patches for them.

So `tools/mongodb.py` carries `FLOOR = (6, 0)` and the flags do only the half they can do — telling
an LTS line from the rapid releases between them, which carry `continuous_release` and live a few
months. Which lines upstream supports is upstream's fact and would go stale if it were copied here;
which of them can be offered *whole* is this repository's, and upstream states it nowhere.

**Below 6.0 a line cannot be offered whole, and the reason is macOS.** Upstream withdrew it from
both surviving older lines while they were still being patched:

| Line | Last patch with a macOS build | Newest patch | macOS there |
| --- | --- | --- | --- |
| 5.0 | 5.0.31 | 5.0.34 | none of any kind |
| 4.4 | 4.4.29 | 4.4.31 | none of any kind |

That is the shape [MySQL](mysql.md) has, where this repository answered it by compiling eight cells
itself. It is not worth answering twice: MySQL's legacy lines are what somebody's 2016 PHP
application needs, and a 2020 MongoDB is not. macOS on Apple Silicon also begins at 6.0, so the
floor is where the row stops needing an exception.

## The Windows archive is mostly not a database

Measured on `mongodb-windows-x86_64-8.3.11.zip`, read out of the zip's own central directory —
**923.3 MB over twelve entries**:

| Entry | Compressed | Shipped |
| --- | ---: | --- |
| `bin/mongod.pdb` | 493.1 MB | no |
| `bin/mongos.pdb` | 350.5 MB | no |
| `bin/mongod.exe` | 32.5 MB | yes |
| `bin/mongos.exe` | 21.8 MB | yes |
| `bin/vc_redist.x64.exe` | 25.4 MB | no |
| `bin/Install-Compass.ps1` | ~0 | no |
| four licence documents | ~0 | yes |

**843.6 MB of it is debug symbols**, which is
[*one version means one thing, and no more than is needed*](../one-version-means-one-thing.md) at
its plainest. The published artifact is **54.1 MB**.

Three of those removals are worth being precise about, because each is a different kind of thing:

- **The `.pdb` files are not caught by `borrow.undebugged`.** That function reads DWARF sections
  *inside* binaries, and a `.pdb` is a separate file — so the rule that would have failed this
  build cannot see it. The removal is the recipe's own decision and is declared in
  `upstream.removed` rather than left to be inferred from a size.
- **`vc_redist.x64.exe` is an installer, and an artifact does not carry one.** The precondition it
  exists to satisfy becomes `requires.vcredist` instead, measured off `mongod.exe`'s import table —
  `vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`, `msvcp140_1.dll`, which is the 2015-2022
  family, declared as its newest member because installing that satisfies any of them. Read off the
  binary for the reason [MySQL's](mysql.md) `msvcr100.dll` had to be: a line's documentation and its
  binaries disagree, and the binaries are what fails to start.
- **`Install-Compass.ps1` downloads a different product.** So does `bin/install_compass` on the
  Unix cells, which is the same file under another name, and both go — which is also what keeps the
  five cells holding the same set of files.

## The Unix cells, and the 45.6 MB Windows never had

Upstream publishes DWARF in a separate `debugsymbols` tarball, so the Unix binaries carry none. What
they do carry is their symbol tables: in `mongod` alone, `.symtab` and `.strtab` are **45.6 MB** of a
169.5 MB binary. Windows ships no equivalent once the `.pdb` files are gone, so `strip.symbols`
levels the four down to the one — the decision [P4b](../roadmap-history.md) made on the Python row —
using `strip.IMAGES` rather than flags chosen here, because two recipes stripping their own binaries
by their own rules would disagree about the same file and nothing outside either could notice. What
it changed is recorded in `upstream.changed`, path by path, with the command that changed it.

## Which Linux build, decided by reading the binary

Upstream builds MongoDB per distribution, and the builds differ in something that matters more than
their names: which OpenSSL they expect the machine to have. Measured on 8.3.11, x86_64:

| Build | Highest glibc symbol referenced | Wants from the system |
| --- | --- | --- |
| `rhel8` (unpacks as `rhel88`) | 2.25 | `libssl.so.1.1`, `libcrypto.so.1.1`, `libcurl.so.4` |
| `rhel93` | 2.34 | `libssl.so.3`, `libcrypto.so.3`, `libcurl.so.4` |

The lower floor is the one that needs **OpenSSL 1.1.1, unpatched since September 2023**. Two glibc
versions of extra reach is not what this repository trades a TLS library's security support for.

So the recipe holds a criterion rather than a name — *the lowest glibc floor among the builds that
link OpenSSL 3* — and settles it by reading `DT_NEEDED` out of the `mongod` it just downloaded. It is
read with `struct` rather than through `relocate.elf_dependencies`, which shells out to `ldd` and so
answers only on Linux: a choice that can only be checked on the platform it is made for is a choice
nobody reviews.

A name written into the recipe would also have gone stale immediately. `rhel93` has no `aarch64`
build below 8.2, and `rhel90` exists on 6.0 and 7.0 and not on 8.x:

| Line | Candidates upstream actually built (either architecture) |
| --- | --- |
| 6.0 | `rhel8`, `rhel90`, `ubuntu2004`, `ubuntu2204` |
| 7.0 | `rhel8`, `rhel90`, `rhel10`, `ubuntu2004`, `ubuntu2204` |
| 8.0, 8.3 | `rhel8`, `rhel93`, `rhel10`, `ubuntu2004`, `ubuntu2204`, `ubuntu2404` |
| 8.2 | `rhel8`, `rhel93`, `ubuntu2004`, `ubuntu2204`, `ubuntu2404` |

**This costs one wasted download per Linux leg** — `rhel8` is fetched, measured, found to want
OpenSSL 1.1.1 and rejected — and that is the price of the choice being a measurement. If upstream
ever rebuilds `rhel8` against OpenSSL 3, this recipe takes it without being edited.

The libraries it does name are bundled: both binaries already carry `RUNPATH=$ORIGIN/../lib`, so
`relocate.bundle` copies `libssl.so.3`, `libcrypto.so.3` and `libcurl.so.4` into `lib/` with nothing
to rewrite, and `relocate.verify` is what then says nothing in the tree resolves outside it. The
glibc floor in `requires` is measured after that, because the floor of an artifact is the highest
floor of anything in it, the libraries it carries included.

## `requires.cpu`, which the index could not say before

**MongoDB has refused to start on an x86_64 without AVX since 5.0** — Intel before Sandy Bridge, AMD
before Bulldozer. The index could state which C runtime, which macOS and which glibc an artifact
needs, and could not state this, so `requires.cpu` was added to
[`index.schema.json`](../../schema/index.schema.json) as an optional enum. `schema` stays at `1`:
that document's own rule is that adding an optional field is not a change a current client cannot
read, and the published index — 62 packages, 330 artifacts — validates against the grown schema
unchanged.

It is the third precondition here measured off the binaries rather than read off a release note, and
unlike `vcredist` and `glibc` it is not a version but a capability: there is no *or newer* to
compare against. Every cell of every line offered carries it.

## What the artifacts promise

```
provides   { "mongod": "bin/mongod[.exe]", "mongos": "bin/mongos[.exe]" }
requires   cpu "avx" everywhere; vcredist on Windows; glibc on Linux; macos on macOS
upstream   project "mongodb/mongo", release <the release's public_githash>
smoke      relocated, and a server that ran
```

`lib/` exists on the two Linux cells and nowhere else. Everything else is identical across the five.

## Licence, and where the source stays

**MongoDB Community Server is SSPL v1** — every release after 16 October 2018, which is every release
offered here. There is no AGPL option: only versions from before that date are AGPL and none of them
are packaged.

SSPL permits what this repository does. Its obligations bite on *offering the program as a service*,
which nothing here does, and it is otherwise a copyleft in GPLv3's shape — the corresponding source
has to stay reachable for what is conveyed. The route is [Redis's](redis-memcached.md), which spans
the same kind of licence: nothing is patched, so the manifest naming exactly what was taken is the
whole of the claim. Here that naming is unusually strong, because the catalogue publishes a
`public_githash` per release and `github.com/mongodb/mongo` carries the matching tag — a reader goes
from the archive to the commit it was built from without trusting a sentence in a document.

No source tarball is mirrored into this repository's releases. It was weighed: it would make the
source promise as durable as the artifact promise, at roughly a hundred megabytes per version, and it
is not what the Redis row does. If that reasoning changes it changes for both rows at once.

## No end-of-life dates, on purpose

MongoDB publishes its lifecycle as an HTML table and nothing else — no JSON, no API, no document
`eol.py --check` could prove a transcription against. `data/eol.json` holds six kinds because six
publishers offer a machine-readable one, and a seventh entry transcribed by hand from a web page is
precisely what [P10](../roadmap-history.md) was written to stop. So `mongodb` carries no `eol` in the
index, like `mysql`, `redis`, `memcached`, `nginx` and `caddy`, and
[*dates are the one claim here that is not about bytes*](../end-of-life-dates.md) says why that is a
decision rather than an omission.

## The shell is a different package

Through 5.0 a MongoDB archive contained a `mongo` shell. From 6.0 it contains none, and `mongosh` is
published from its own repository, on its own release clock, under **Apache-2.0** against the
server's SSPL v1.

So it is a second kind here rather than a second directory inside this one. Two products under one
version number could not answer whose version it was, which is the whole of *one version means one
thing*; and a shell release should not have to wait for a server release to reach anybody. It has the
same five cells and the same absent sixth, and `provides` is `{"mongosh": "bin/mongosh"}`.

Its Linux asset is the one with **no OpenSSL suffix**. Upstream publishes three — one per system
OpenSSL, plus one carrying its own — and the self-contained one costs about 4 MB against `-openssl3`
and buys an artifact with nothing to bundle and no opinion about the machine it lands on, which is
the trade the [Python](python.md) row makes for the same reason.

**The server's smoke test does not use it.** `mongodb_smoke.py` speaks an `OP_MSG` carrying
`{hello: 1}` over a socket instead, in about forty lines of `struct`, because a server test that
needs a separately released package goes red for reasons that are not about the server — and on a
day `mongosh` has no build for a cell, that cell's server would become unprovable.
