# Meilisearch

*Part of [mixengine-packages](../../README.md), which holds the table of what is packaged.*

A search engine that is one file, borrowed on five cells:

| OS / arch | Range | How |
| --- | --- | --- |
| Windows x86_64 | **1.53.2 – newest packed** | **borrowed** — `meilisearch-windows-amd64.exe`, the Community Edition |
| Windows aarch64 | — | upstream has never built one |
| macOS aarch64 | ditto | `meilisearch-macos-apple-silicon` |
| macOS x86_64 | **per release** | `meilisearch-macos-amd64` — absent from v1.53.2 |
| Linux x86_64, aarch64 | ditto | `meilisearch-linux-amd64`, `meilisearch-linux-aarch64` |

The design, and what was measured before the recipe was written, is
[the spec](../superpowers/specs/2026-09-17-meilisearch-packaging-design.md).

## Which binary, and what a line is

**The Community Edition, and only it.** Every release publishes a `meilisearch-<target>` and a
`meilisearch-enterprise-<target>`, and the repository is `MIT AND BUSL-1.1`. Upstream's release
workflow passes `--features enterprise` to the second build alone, so the first is compiled without the
Business Source code. The artifact carries `LICENSE-MIT` from the release's own tag, declared in
`upstream.added`, and no `LICENSE-EE`.

**There are no maintained lines.** Meilisearch ships a minor about every two weeks — 42 in the 100
stable releases from v1.12.5 to v1.53.2 — and does not go back to patch old ones. So the minor is a line
for the README table, which shows the newest fifteen; **nothing is back-filled**, and a release is packed
when somebody asks for it rather than because upstream shipped it. Every release packed stays in the
archive forever, and at five cells of about 90 MB each that is the cost a dispatch commits to.

**Which cells a release has is read off that release**, as `caddy.py` does. v1.53.2 has no macOS
x86_64 binary although its enterprise twin and every earlier release do; that leg exits 75 and the other
four publish.

## What the size is

v1.53.2's binaries are 326–335 MB where v1.53.1's were 116–127 MB. **It is not debug information.**
The whole difference is read-only data — `.rodata` is 77.2 MB in 1.53.1 and 296.1 MB in 1.53.2, `.text`
is 36 MB in both — in the release that updated the tokenizer, `charabia`, to 0.10.0. Nothing is
stripped, and the data compresses: 350 MB becomes about 90 MB in the artifact.

**The digest is GitHub's.** Meilisearch publishes no checksums; the release API reports a SHA-256 for
every asset, computed at upload, and `upstream.verified_against` says that is what the download was
checked against.

## What the daemon has to know

- **Start it with `--no-analytics`.** Meilisearch reports anonymous usage by default.
- **A data directory belongs to the version that wrote it.** Moving a project to another version
  needs `--upgrade-db` (from 1.51; `--experimental-dumpless-upgrade` before it), and a database older
  than 1.12 needs a dump instead. There is no downgrade.
- **Windows needs the Visual C++ 2022 redistributable**: the executable imports `VCRUNTIME140.dll` and
  ships nothing beside it, so `requires.vcredist` says so.

## What is proven

From a directory the file has been moved to: `--version` names the release; the server starts with
`--env development --no-analytics` and every path it writes under a temporary directory; `/health`
answers `available` and `/version` the release; a document is added, its indexing task succeeds, and a
search finds it; the server stops. Asked to be a version it is not, the test refuses at the first step.

**No end-of-life dates**: no LTS, no support policy, no document.
