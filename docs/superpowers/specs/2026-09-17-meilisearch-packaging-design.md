# Meilisearch, a service that is one file and forty versions

*Design for a proposed **P22**. It settles which edition is packed, what a line is for a project that
ships a minor release every fortnight, where each cell comes from, and what the artifact promises. The
service recipe — a data directory, a port, a master key or the absence of one — is MixEngine's.*

---

## Why this row exists at all

Laravel Scout, Symfony and most PHP full-text search integrations name Meilisearch as a driver, and
the PHP this index ships reaches it over HTTP with nothing to install. So, as with MongoDB, the index
already makes every PHP able to talk to one and offers nothing to talk to.

And it is cheap in the way Caddy is cheap: every cell upstream publishes is **one executable with
nothing beside it**.

What the row does **not** have behind it is blueprint demand, and this document does not claim any.

## Which edition

Every release publishes two binaries per target: `meilisearch-<target>` and
`meilisearch-enterprise-<target>`. The repository's `LICENSE` reads `SPDX-License-Identifier: MIT AND
BUSL-1.1`: the Enterprise Edition parts are under the **Business Source License 1.1**, and the rest is
MIT.

**What separates the two binaries is a Cargo feature, and that was read rather than inferred.**
`.github/workflows/publish-release-assets.yml` builds a matrix of `edition: [community, enterprise]`,
and only the enterprise leg passes `--features enterprise`. So the Community binary is compiled without
the BUSL code. **Only the Community Edition is packed**, and the manifest says so; a BUSL binary is a
licence whose terms change on a date, and nothing a local development environment reaches for is in
it.

## What is offered

| Version | macOS aarch64 | macOS x86_64 | Linux x86_64 | Linux aarch64 | Windows x86_64 | Windows aarch64 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1.x** | ✅ | ✅ \* | ✅ | ✅ | ✅ | — |

**Windows on ARM is upstream's empty cell.** The release matrix builds `windows-2022` only; there has
never been an aarch64 Windows binary. `linux-riscv64` is published and is not a cell here.

\* **Which cells a release has is read off that release's own asset list, the way `caddy.py` does it.**
`v1.53.2` (2026-09-07) has no `meilisearch-macos-amd64` although its enterprise twin and every earlier
release have one, and the workflow still names a `macos-15-intel` leg. That is a missing asset rather
than a withdrawn platform, and a recipe that states floors of its own would get it wrong in one
direction or the other; so, like Caddy, it states none, and a release missing a cell leaves that cell
empty for that release.

## What a line is, which is the decision this row actually needs

**Meilisearch has no LTS and no maintained older lines.** In the 100 most recent stable releases —
`v1.12.5` on 2025-01-20 to `v1.53.2` on 2026-09-07 — there are **42 minor versions**, about one every
two weeks, and patches almost never go back more than one minor.

A *line* decides two things here — the README table and `eol.dated` — and this kind has no dates.
The README table is no longer a cost either: the README shows **at most the fifteen newest lines** of
any package, one row per line, so a kind that adds a minor every fortnight keeps a fifteen-row table
and the full list lives on `docs/packages/meilisearch.md`.

**What is left is the cost per release, and the index keeps every one forever**: roughly 120 MB per
cell times five cells — about 600 MB each time a release is packed, or about 1.6 GB if the size jump
under *What the rule takes out* cannot be stripped. Packing every stable release upstream publishes,
at the rate of the last twenty months, is on the order of **37 GB a year** that can never be deleted.

**Decided: the minor is the line, the floor is whatever is newest on the day the first release is
packed, and releases are packed on demand.** The minor is the line because it is where the database
format changes: a data directory written by one minor is not simply opened by another (see *What the
artifact promises*), and that is the unit a blueprint has to pin. Starting at the newest rather than
back-filling forty lines is a statement that nobody needs a 2025 Meilisearch pinned; if somebody does,
adding a line is one dispatch.

**On demand is not a special case for this row, it is every row's rule.** No kind here follows its
upstream on a clock: every build is dispatched by hand, as `docs/adding-a-version.md` describes, and
the scheduled workflows only *check* — dates, the archive, the blueprint gallery, the extension
registry. Making the one kind that releases most often the first to be packed automatically would
turn the permanence promise into the most expensive thing in this repository for the least reason.

## Where each cell comes from

GitHub releases of `meilisearch/meilisearch`. There is no `SHA256SUMS` file among the assets, so the
digest is **the `digest` field GitHub's release API reports for each asset** (`sha256:…`). That is
weaker than every other borrowed row here: it is a hash GitHub computed at upload, not a document the
publisher wrote. It is recorded as such in `upstream.verified_against` rather than presented as
something it is not. If upstream ever publishes checksums of its own, the recipe switches to them.

## What the rule takes out

**Nothing can be taken out of one file, and something might still have to be.** The Community binaries
were 116–127 MB in `v1.53.1` (2026-08-13) and **326–335 MB in `v1.53.2`** (2026-09-07), a patch
release, on every target at once. Cargo's `release-with-debug` profile sets `debug = true`; a
2.7-times jump in a patch release on every platform is the size DWARF makes. This is a hypothesis, not
a measurement, and it is the first thing on the list below. If it holds, `strip.py` removes it and
declares it in `upstream.changed`, exactly as P6b and P4b settled for every other row, and the
artifact is levelled back to the size of the binaries before it.

## What the artifact promises

```
kind        "meilisearch"
provides    { "meilisearch": "meilisearch[.exe]" }
source      "borrowed"
upstream    { url, sha256 (GitHub asset digest), verified_against,
              project: "meilisearch/meilisearch", release: "v<version>" }
requires    glibc   Linux, measured — built on ubuntu-22.04, so expected at or below 2.35
            macos   measured
            vcredist  Windows, measured
smoke       { relocated: true, ran: [...] }
```

- **The upstream asset is a bare executable, not an archive**, so the artifact is that one file under
  the name `meilisearch[.exe]`, beside the manifest and `LICENSES.md`. Composer's phar set the
  precedent for a payload that has no layout to preserve; renaming the platform suffix off the file is
  the least that makes `provides` the same on every cell.
- **Meilisearch sends anonymous analytics by default.** The daemon should start it with
  `--no-analytics` (or `MEILI_NO_ANALYTICS=true`). Named here because it is a fact about this binary
  that a user of a local environment would not expect.
- **A data directory belongs to the version that wrote it.** Opening one with a different minor is
  refused unless an upgrade is asked for, and there is no downgrade. So a MixEngine project that changes
  its pinned minor has a migration to run, not just a binary to swap. The exact behaviour — which flag,
  from which version, and what it refuses — is measured before this contract is final.

## Licence

MIT for the Community Edition binary, as above. `LICENSES.md` says which edition and quotes the
`LICENSE-MIT` text; the absence of `LICENSE-EE` in the artifact is the point.

## No end-of-life dates, on purpose

No LTS, no support policy, no document. `meilisearch` has no `eol` field.

## How it is proven

The service shape Caddy's smoke already has: move the file, start it on a free port with
`--db-path` in a temporary directory, `--no-analytics` and `--env development` (so no master key is
required), wait for `GET /health` to answer `{"status":"available"}`, check that `GET /version` reports
the manifest's version, create an index, add one document, wait for the task to succeed, search for it,
then stop the process and confirm it is gone.

## What this does not do

- **No Enterprise Edition.**
- **No back-filled lines**; see *What a line is*.
- **No `meilisearch.deb`, OpenAPI document or error-code catalogue** — not a cell, not a program.
- **Nothing in MixEngine.**

## What is left to measure before a line of the recipe is written

1. What the 210 MB added in `v1.53.2` is: DWARF, a symbol table, or something embedded — and whether
   stripping it leaves a binary whose loader view is unchanged.
2. The minimum macOS on both architectures, and the glibc floor on both Linux ones.
3. The Windows import table, for `vcredist`.
4. The data-directory rule across minors: which version introduced the in-place upgrade, what flag it
   takes today, and the exact refusal a downgrade prints.
5. Whether a Windows runner's administrator token changes anything, since P12a found that it did for
   PostgreSQL.

## The task

**P22 — Meilisearch**: `tools/meilisearch.py`, `.github/workflows/build-meilisearch.yml`,
`docs/packages/meilisearch.md`, a row in the README table, and the absence in `eol.py`'s docstring.
