# Go

*Part of [mixengine-packages](../../README.md), which holds the table of what is packaged.*

The one runtime here that asks for nothing to be built, and one recipe for every cell:

| OS / arch | Range | How |
| --- | --- | --- |
| Windows x86_64, aarch64 | **1.21 – newest** | **borrowed** — official `go<version>.windows-<arch>.zip`, repacked |
| macOS aarch64, x86_64 | **1.21 – newest** | ditto, the `darwin` tarballs |
| Linux x86_64, aarch64 | **1.21 – newest** | ditto, the `linux` tarballs |

Every cell is upstream's and none is empty: `go.dev/dl/?mode=json&include=all` lists an archive for
all six targets on every stable release from 1.21, and its first Windows-on-ARM archive is
`go1.17beta1`. That same document carries the SHA-256 of every file, so `tools/go.py` takes the
version, the file and the digest out of one entry. The design, and what was measured before a line of
the recipe was written, is [the spec](../superpowers/specs/2026-09-17-go-packaging-design.md).

**The floor is 1.21, and it is a decision rather than upstream's.** From 1.21 every release is
`go1.N.P`; below it a line's first release is `go1.20`, which the index cannot sort as a patch of its
line. It is also the release that gave the `go` command `GOTOOLCHAIN` — the setting the next section
is about. Upstream supports only the two newest lines, and a newer `go` builds an older module, so
the reason to offer 1.21 to 1.25 is a blueprint that pins one.

## What goes

Almost nothing, because `src/` looks like source and is not optional — `go build` compiles the
standard library out of it. What goes is what only Go's own build and tests read:

- **`api/`, `test/` and `doc/`** at the root. No non-test `.go` file under `src/` of 1.21.13 or
  1.27.1 joins `GOROOT` to any of them.
- **Every `testdata/` directory under `src/`** — 112 on 1.27.1, 97 on 1.21.13. They are the fixtures
  of the standard library's own tests, and the reason this is not merely tidiness is what is inside
  them: **30 of the 53 binaries under `testdata/` carry DWARF** on 1.27.1. `borrow.publish` refuses a
  tree holding any binary with debug information, and `strip.debug` would satisfy it by rewriting
  upstream's test fixtures, which exist to be exactly those bytes.

That is 36.6 MB of 1.27.1's 246.9 MB tree, and 30.2 MB of 1.21.13's, declared in `upstream.removed`.
**`misc/` stays**, at 0.1 MB, because before 1.24 it holds the WebAssembly launcher
`misc/wasm/go_js_wasm_exec`, which moved to `lib/wasm/` from 1.24 — a delete-list right for the newest
line and wrong for the oldest is the thing `node.py`'s docstring warns about.

**The `.syso` objects are never stripped.** They are linked into every program a user builds with
`-race` or BoringCrypto, so they are upstream's bytes or nothing. The recipe asks each one for debug
information *before* `strip.debug` runs, and refuses the cell rather than rewrite one; the answer to a
refusal there is a `keeps` entry with that reason.

## `GOTOOLCHAIN`, which is the daemon's half

**`go.env` is kept byte for byte**, and it says `GOTOOLCHAIN=auto`. With that setting, a `go` from
this archive that meets a `go.mod` asking for a newer Go downloads that Go into the module cache and
runs it instead — so a project pinned to 1.25 would silently build with whatever its `go.mod` names.
That is not a defect in the artifact; it is the setting that decides whether pinning a version means
anything, and it belongs to whoever renders a project's environment. **MixEngine sets
`GOTOOLCHAIN=local`.** An archive edited to say so would be a Go that behaves unlike the version it
names, and *repack, do not rearrange* rules that out.

## What is proven

`GOROOT` is derived from where `bin/go` is, so nothing is relocated — and a moved Go that cannot find
its standard library still answers `go version` with a constant. So the smoke test moves the tree and
then makes it work: `go env GOROOT` has to be the moved path, and `go build` has to compile a program
importing `fmt`, `crypto/sha256` and `net/http`, which then has to print this Go's own
`runtime.Version()`. It runs with `GOTOOLCHAIN=local`, `GOPROXY=off`, `GOENV=off`, `CGO_ENABLED=0`
and every `GO*` variable of the runner removed, so neither the network nor the runner's own Go can
answer for it. Hiding `src/fmt` in the moved tree turns that into `package fmt is not in std`, which
is the failure the test exists to be able to produce.

No `requires` is expected on Windows or Linux — Go binaries import only the Windows API, and the
distributed `go` is statically linked — and macOS carries whatever its load commands state, read by
`relocate.floor`.

**No end-of-life dates.** Go states its policy as a sentence — a release is supported until two newer
major releases exist — and dates nothing, so `go` has no `eol` in the index.
