# Go, the runtime that asks for nothing to be built

*Design for a proposed **P19**. It settles the packaging half: which lines are offered, where each
cell comes from, what the rule takes out, and what the finished artifact promises a daemon. How
MixEngine puts `go` on a `PATH`, and which environment it renders around it, is that repository's
work — but the one environment variable that decides whether this package means anything is named
here, because it is a fact about the archive.*

---

## Why this row exists at all

The index offers four language runtimes — PHP, Node.js, Python, Ruby — and every one of them cost a
recipe that chose, stripped or compiled something. Go is the runtime that does not: upstream
publishes one relocatable archive per cell, for all six cells, with a SHA-256 for each in a single
machine-readable document. It is the cheapest runtime this repository could add, which is an
argument for adding it only if somebody reaches for it; it is written down first among the five
proposals because it is the one whose cost is almost entirely the evaluation below.

What the row does **not** have behind it is blueprint demand, and this document does not claim any.

## What is offered

Seven lines, floor at **1.21**, every cell borrowed:

| Version | macOS aarch64 | macOS x86_64 | Linux x86_64 | Linux aarch64 | Windows x86_64 | Windows aarch64 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1.21** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **1.22** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **1.23** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **1.24** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **1.25** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **1.26** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **1.27** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Every cell is upstream's, and none is empty.** Read off `https://go.dev/dl/?mode=json&include=all`
on 2026-09-17: 365 releases, the newest `go1.27.1`, and every stable release carries an `archive` for
`darwin-arm64`, `darwin-amd64`, `linux-amd64`, `linux-arm64`, `windows-amd64` and `windows-arm64`.
The first `windows-arm64` archive in that document is `go1.17beta1`, so nothing at or above the floor
is missing a cell.

**The floor is 1.21 because that is where a Go version became a three-part number.** Below it the
first release of a line is `go1.20`, not `go1.20.0`, and the release candidates are `go1.20rc1`.
From 1.21 every release is `go1.N.P`, which is what `mkindex.py` sorts and what `eol.dated` would
call a line. 1.21 is also the release that gave `go.mod` its `toolchain` line and the `go` command
its `GOTOOLCHAIN` behaviour — the part of this document MixEngine has to act on. Offering 1.20 and
below would need a version rewrite in the recipe and would ship a `go` that has never heard of the
setting that keeps it honest.

That floor is this repository's choice rather than upstream's, and it is **decided**. Go supports only
the two newest lines, and a newer `go` builds an older module — so the case for 1.21–1.25 is a
blueprint that pins one, not a compatibility gap, and it was weighed against offering only 1.26 and
1.27 and judged worth the storage.

## Where each cell comes from

`go.dev/dl/?mode=json&include=all`. One entry per file carries `filename`, `os`, `arch`, `version`,
`sha256`, `size` and `kind`, so the version, the URL and the digest come from one document — the
shape `redis.py` has with `redis-hashes`. The recipe takes `kind == "archive"`: `.tar.gz` on macOS
and Linux, `.zip` on Windows. The `.pkg` and `.msi` installers are ignored.

## What the rule takes out

Measured on `go1.27.1.windows-amd64.zip`: **75.3 MB compressed, 235.5 MB unpacked, 15,639 entries**,
all under one `go/` directory.

| Directory | Unpacked | Read by a running `go`? |
| --- | ---: | --- |
| `src/` | 126.1 MB | yes — the standard library is compiled from it; `src/cmd` alone is 51.7 MB |
| `pkg/tool/` | 71.3 MB | yes — `compile` 27.4 MB, `vet` 9.1, `fix` 9.4, `link` 7.2, `cover` 5.8, `asm` 5.4, `cgo` 4.5, `preprofile` 2.5 |
| `bin/` | 19.9 MB | yes — `go` 16.7 MB, `gofmt` 3.2 MB |
| `api/` | 8.6 MB | no — the API compatibility lists, read by `cmd/api` during Go's own `all.bash` |
| `test/` | 7.5 MB | no — Go's own compiler test suite, read by `go tool dist test` |
| `lib/` | 1.7 MB | yes — `lib/fips140`, `lib/time`, and `lib/wasm` from 1.24 |
| `doc/` | 0.4 MB | no — the specification and memory model as HTML |
| `misc/` | 0.1 MB | yes, on lines before 1.24 — `misc/wasm/go_js_wasm_exec` |
| `go.env`, `VERSION`, licences | ~0 | yes |

**Unlike every runtime packed so far, almost all of it stays.** `src/` looks like source and is not
optional: `go build` compiles the standard library out of it, and removing any part of it breaks a
program somebody imports that package into.

**`api/`, `test/` and `doc/` go — about 16.5 MB of 235.5, or 7%.** Every non-test `.go` file under
`src/` of 1.27.1 was searched for a path joining `GOROOT` to any of the four candidates, and nothing
matched: `api/` is read by `cmd/api` and `test/` by `go tool dist test`, both only while Go builds and
tests itself, and `doc/` is the language specification as HTML. **`misc/` stays**, at 0.1 MB, because
it is not dead on every line: before 1.24 the WebAssembly launcher `go_js_wasm_exec` lived in
`misc/wasm/`, and from 1.24 it moved to `lib/wasm/`, which stays for the same reason. A keep-list
that is right for 1.27 and wrong for 1.21 is the one `node.py` warns about. What goes out is declared
through `borrow.declare` as `upstream.removed`, the same as every other row.

**And the 112 `testdata/` directories under `src/` go too — 4,249 files, 17.9 MB — which the table
above cannot show because they are spread through the tree.** They are the fixtures of the standard
library's own tests, read by `go test` of `debug/elf`, `archive/zip` and the rest and by nothing a
user builds. The reason they are not merely surplus but a problem is what is inside them: running
this repository's own `relocate.kind` and `strip.debug_sections` over the 1.27.1 Windows tree finds
**53 binaries under `testdata/`, 30 of them carrying DWARF**. `borrow.publish` refuses a tree holding
any binary with debug information, and `strip.debug` on Linux would rewrite upstream's test fixtures to
satisfy it — a modification to files whose whole purpose is to be exactly those bytes. Removing them
is the one answer that is true on all six cells.

**What the same pass found clean, and has to stay clean:** `bin/` (2 binaries) and `pkg/tool/` (8)
carry no debug information on Windows, and the 14 `.syso` objects under `src/runtime/race` and
`src/crypto/internal/boring/syso` carry none either. Those `.syso` files are linked into every program
a user builds with `-race` or BoringCrypto, so they are upstream's bytes or nothing — if a Unix cell
turns out to carry DWARF in them, that is a `keeps` entry with that reason, never a strip. Total
removed: **34.4 MB of 235.5, about 15%**.

**Nothing is stripped.** Whether the Go tool binaries carry DWARF is a question
[P6b](../../roadmap-history.md)'s check answers for this row the way it answers for every other one;
if they do, `strip.py` removes it and declares it, and if they do not, there is nothing to do.

## What the artifact promises

```
kind        "go"
provides    { "go": "bin/go[.exe]", "gofmt": "bin/gofmt[.exe]" }
source      "borrowed"
upstream    { url, sha256 (both from go.dev/dl JSON), project: "golang/go",
              release: "go<version>" }
requires    macos     measured from LC_BUILD_VERSION on bin/go
            glibc     Linux, measured — expected to be absent, see below
smoke       { relocated: true, ran: [...] }
```

Four things the contract says out loud:

- **The `go/` wrapper directory is not kept**, which is `borrow.unpack`'s rule for every runtime: the
  daemon unpacks straight into `runtimes/go/<version>/`, and `provides` is relative to that.
- **`GOROOT` is wherever the archive is.** The `go` command has derived `GOROOT` from its own
  executable's location since 1.10, so nothing is relocated and no path is rewritten. The smoke test
  proves it rather than this sentence: it moves the tree and asks `go env GOROOT`.
- **The archive's `go.env` is kept exactly as upstream wrote it**, including `GOTOOLCHAIN=auto` and
  `GOPROXY=https://proxy.golang.org,direct`. *Repack, do not rearrange* says so, and a `go.env` edited
  here would be a Go that behaves differently from the one its version number names.
- **With `GOTOOLCHAIN=auto`, the `go` in this archive will download a different Go** whenever a
  module's `go.mod` asks for a newer one, and run that instead, from the module cache. A MixEngine
  project pinned to 1.25 would silently build with 1.27. That is not a defect in the artifact; it is
  the setting that decides whether pinning a version means anything, so the daemon has to render
  **`GOTOOLCHAIN=local`** into the environment it gives a project. Named here because it is a fact
  about this archive; decided over there because that is where environments are rendered.

**No `requires.vcredist`.** Go binaries on Windows import only the Windows API — measured off
`go.exe`'s import table, not assumed from the language — and **no `requires.glibc` is expected** on
Linux, where the distributed `go` is statically linked. Both are measured; if either turns out
otherwise, the field is written, because a precondition that exists and is not declared is one the
user meets.

## Licence

BSD-3-Clause, with the `PATENTS` grant beside it, both inside the archive and kept. Nothing is
compiled here, so there is no source obligation to meet beyond naming the release, which
`upstream.release` does.

## No end-of-life dates, on purpose

Go's support policy is one sentence — *each major release is supported until there are two newer
major releases* — and it is published as prose. The download document carries a `stable` flag and no
date. A date derived here from that sentence and a release calendar would be exactly the
transcription [P10](../../roadmap-history.md) exists to stop, so `go` joins `mysql`, `redis`,
`memcached`, `nginx`, `caddy`, `mongodb` and `mongosh` with no `eol` field in the index.

## How it is proven

`tools/go_smoke.py`, or a `smoke` inside `tools/go.py` if it stays as short as Caddy's:

1. Unpack, then move the tree somewhere unrelated.
2. `go version` answers the version the manifest names.
3. `go env GOROOT` answers the moved path.
4. Build and run a one-file program that imports `fmt`, `net/http` and `crypto/sha256`, with
   `GOTOOLCHAIN=local`, `GOPROXY=off`, `GOFLAGS=-mod=mod`, `CGO_ENABLED=0`, and `GOCACHE` and
   `GOPATH` inside the work directory — so the test cannot reach the network and cannot be answered
   by a Go that is not the one in the archive.

`CGO_ENABLED=0` is on purpose: a runner's C compiler is not part of the artifact, and a smoke test
that needs one is a test that can go red for a reason that has nothing to do with the archive.

## What this does not do

- **No Go below 1.21.** Stated as a floor, not attempted.
- **No `rc` channel.** The document lists `go1.27rc3`; the index can carry it the day it is wanted.
- **No `gopls`, `dlv`, `staticcheck` or any other tool.** They are separate release trains, installed
  with `go install` into a user's `GOPATH`, and none is part of the distribution.
- **Nothing in MixEngine.** `GOTOOLCHAIN=local`, `GOPATH`, `GOCACHE` and the module cache location
  are that repository's work.

## What is left to measure before a line of the recipe is written

1. The same search for `api/`, `test/` and `doc/` on **1.21**, which has only been done on 1.27.1.
2. DWARF in `bin/`, `pkg/tool/` and the `.syso` objects on the four Unix cells — P6b's check, which
   has only been run on Windows x86_64.
3. The macOS floor from `LC_BUILD_VERSION`, on both architectures and every line; Go raises it on its
   own schedule, so it is expected to differ between 1.21 and 1.27.
4. `go.exe`'s import table on both Windows architectures, and `DT_NEEDED` on both Linux ones.
5. The size of the whole row: seven lines of roughly 75 MB per cell and one archive per patch release
   is the largest per-release footprint of any borrowed runtime here, and it should be stated before
   the first release rather than discovered in the archive's total.

## The task

**P19 — Go**: `tools/go.py`, `.github/workflows/build-go.yml`, `docs/packages/go.md`, a row in the
README table, and the absence in `eol.py`'s docstring. Nothing in `mkindex.py`, `parity.py`,
`permanence.py`, `borrow.py`, `strip.py` or `relocate.py` changes.
