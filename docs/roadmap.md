# mixengine-packages build plan

This repository releases on its own clock, so it needs its own order of work. What is here is that
order: where the pipeline stands, what every closed task settled, and what is left.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · **(rule)** = a conformance debt against
[*One version means one thing, and no more than is needed*](one-version-means-one-thing.md).

---

## Where we are

Every row of the runtime table is packed, and every service row that has been evaluated is packed.
Every recipe now conforms to the rule and there is a program that says so. What is *not* done is the
**repack**: the artifacts on the releases page were packed before P2–P5, and `tools/parity.py` names
every one of those differences on every run. [P6](roadmap-history.md) is what it says and what it
does not. PostgreSQL is the first row packed *after* it, and the difference shows three times: the
rule caught an asymmetry inside EDB's own release before anything was published; when a second
publisher was added for the same version it had something to be checked against rather than only a
recipe's word; and when the macOS cells were cut from 362 MB to 82 MB it was the rule that said what
the smaller tree still had to offer, so a saving of that size cost nothing anybody could argue
about.

| Kind | Cells | Recipes | Conforms |
| --- | --- | --- | --- |
| PHP | 7.0 – newest, 6 targets | `php_windows`, `php_unix`, `php_legacy_unix` | yes — P2 |
| Node.js | 16 – newest, 6 targets | `node` | yes — P3 |
| Python | 3.10 – newest, 6 targets | `python` | yes — P4, P4a, P4b and P4c |
| Ruby | 3.2 – newest, 6 targets | `ruby`, `ruby_unix` | yes — P5, P5a, P5b, P5c |
| Caddy | 2.0 – newest, 6 targets | `caddy` | yes |
| MariaDB | 10.6 – newest, 6 targets | `mariadb`, `mariadb_deb`, `mariadb_build` | yes — it is where the rule came from |
| PostgreSQL | 14 – newest, 5 of 6 targets | `postgres`, `postgres_deb` | yes — P7, P7a and P7b, and it is the first row packed under the rule |
| Go | 1.21 – newest, 6 targets | `go` | yes — P19, measured before it was written |
| Java | 11, 17, 21, 25, 6 targets | `java` | yes — P20 |

The rule was written **after** MariaDB, because MariaDB is what taught it: three routes to one
version produced three different feature sets, and fixing that is what
[`10d4e81`](https://github.com/mixnz/mixengine-packages/commit/10d4e81) and
[`6c344d0`](https://github.com/mixnz/mixengine-packages/commit/6c344d0) began. They did not
finish it: a later audit of the six *finished* artifacts of a green run found four more asymmetries
no recipe knew it had, and closing those took seven further commits; what that audit found is
written down in [that rule](one-version-means-one-thing.md),
because it is the argument for P6. The rule had never been applied backwards to the four runtime
rows that were packed before it existed, and P1–P6 were that work. Measured against upstream's own
archives, the gaps were not marginal: PHP 8.3 on Windows was missing two extensions this repository
fails a Unix build over, which P2 closed; Node.js 24.19.0 was 106 MB on Windows against 198 MB on
Linux, which P3 closed; CPython 3.13.15 shipped Tk 8.6 to Windows and Tk 9.0 to Unix under one
version number, which P4 closed by shipping neither; and Ruby 4.0.6 on Windows was 276 MB of which
225 MB was documentation the four compiled cells are configured never to build, which P5 closed.
Four times now a task has come out somewhere other than where it was pointed — P3 kept npm's manual
pages after going and reading npm, P4a keeps 30 MiB of a shared library nothing in the archive
loads, P4b found its own title wrong and two of its stated reasons for existing wrong with it, and
P5a was written to close an asymmetry that a look at the six trees says is not there. That is what a
rule is for, and it is the argument for measuring the artifacts rather than the release notes: every
one of those four was written from what the publisher says and corrected by what the publisher ships.
P5b then said the same thing about a check rather than an artifact — the comparison it added was
correct on paper and wrong on the first real archive it was pointed at. P6 closed the sequence by
turning the audit that started it into a program, and its first run says the same thing a sixth
time: every difference it reports is real, and every one is against an archive packed before the
task that already closes it.

*Packed* above means the recipe is written and runs, which is not the same as published, and the two
had quietly come apart: the releases page held PHP, Node.js, Python, Ruby, Caddy and MariaDB, while
PostgreSQL, Redis, Memcached and nginx had recipes and nothing to install. P12 was that gap, found by
P11 while counting the archive, and it is closed — every kind here is now published. The releases
page holds 60 packages — 55 of them, and then MySQL's five lines, published on 2026-08-20 by P14 —
and it was rebuilt from empty on 2026-08-17 after the repository was deleted and
recreated; [the archive](the-archive.md) carries the record of what that cost.

None of that work was a rewrite. Every recipe already downloads, verifies, relocates, proves and
packs correctly; what they do not do is *choose*, and choosing once is the whole of the rule.

---

## What each task settled

Thirty-six tasks are closed. Each one is kept whole in
[`roadmap-history.md`](roadmap-history.md), because what a task found is usually worth more than
the fact that it is finished; this is the index into it, in the order the tasks were written.

**Conformance — apply the rule to the rows packed before it**

| Task | What it settled |
| --- | --- |
| **P1** | `borrow.declare` — one function writes `upstream.added` and `upstream.removed`, and checks each claim against the tree before writing it. |
| **P2** | PHP: one extension set across six cells, chosen once. Windows gained `redis` and `mongodb`, and lost PHP's own test extensions. |
| **P3** | Node.js: `include/node` is 59 MB no Windows zip has ever carried and `node-gyp` does not read. |
| **P4** | Python: one version was shipping Tk 8.6 to Windows and Tk 9.0 to Unix, so it now ships neither. |
| **P4a** | Python: the Unix cells shipped the interpreter twice; one copy stayed, and `keeps` is where the reason travels. |
| **P4b** | Python: `install_only_stripped` was not stripped. `strip.py` and its structural proof came out of this. |
| **P4c** | Python: what P4b's first run on CI found — two unrelated reds, and the second is why this is not a footnote. |
| **P5** | Ruby: the borrowed half and the compiled half made to answer the same questions. |
| **P5a** | Ruby: the shared library and the linker's half of the archive — one of P5's two claims was a misreading of the tree. |
| **P5b** | Ruby: 37.8 MB of DWARF on Linux and 19.9 MB on macOS, levelled down to the none RubyInstaller ships. |
| **P5c** | Ruby: `strip -S` reassembles a static-library member, which is what four red runs were actually reporting. |
| **P6** | `parity.py` — the rule turned into something CI can fail on, and its first run said the same thing a sixth time. |
| **P6a** | The Windows cells `relocate.verify` was never allowed to look at. |
| **P6b** | Debug symbols were a rule nothing could fail on, because DWARF is bytes inside a file rather than a path. |

**The services**

| Task | What it settled |
| --- | --- |
| **P7** | PostgreSQL: EDB's two archives measured rather than read about; three of the four cells it touched moved. |
| **P7a** | PostgreSQL on Linux from `apt.postgresql.org` — one recipe for both architectures. |
| **P7b** | PostgreSQL: the macOS universal archive sliced, 362 MB of tree to 82 MB, and not one byte re-signed. |
| **P8** | Redis and Memcached: evaluated, and the evaluation came out at *build* on the platform that usually borrows. |
| **P8a** | Redis on Windows — "there is no Windows build system" and "there is no Windows Redis" are two different claims. |
| **P8b** | The licence check that could not fail, because somebody else's licence answered before it was reached. |
| **P9** | nginx: borrowed on Windows, and `nginx -V` there is the specification the other four cells are compiled against. |
| **P14** | MySQL: five lines, and eight cells compiled here because Oracle withdrew macOS while those lines were still alive. |
| **P18** | MongoDB: five LTS lines borrowed from 6.0, a Windows zip that was 91% debug symbols, and seven things only CI could find. |
| **P18a** | `mongosh` published, and a requirement no smoke test could see — the library nothing loads until someone needs it. |

**The tools**

| Task | What it settled |
| --- | --- |
| **P17** | Composer: a phar published like a runtime — six archives of one payload rather than a schema change. |

**The runtimes**

| Task | What it settled |
| --- | --- |
| **P19** | Go: seven lines borrowed whole, and the 112 `testdata` directories that were the only thing standing between it and `borrow.publish`. |
| **P20** | Java: Microsoft's JDK on four LTS lines because Temurin has no Windows ARM64 on three, and `requires.libraries` for what a Linux JDK expects the machine to have. |

**The index**

| Task | What it settled |
| --- | --- |
| **P10** | End-of-life dates for every kind: six publishers, six machine-readable documents, and no mirror. |
| **P11** | The permanence promise proved — what GitHub can enforce, what it cannot, and the key that signs the index. |
| **P12** | Four kinds had finished recipes and no release. Every kind here is now published. |
| **P12a** | PostgreSQL cannot be smoke-tested on a runner that is an administrator. |
| **P12b** | Redis 7.2 builds on Windows and cannot start there, which is why that cell is empty. |
| **P13** | Every published PHP archive predated P2, and was republished rather than argued about. |
| **P15** | Sign the blueprint gallery, and prove the key before signing anything with it. |
| **P15a** | Let the gallery ask for its own check instead of waiting for a clock to come round. |
| **P16** | Publish the extension registry, and hold the key rather than scrape what is published. |

---

## What is left

### [ ] P7c — PostgreSQL on Windows/ARM64, when 19 makes it possible

Blocked on upstream rather than on anything here, and unblocked by a release: PostgreSQL 19 accepts
`aarch64` where 18 does not. When `versions.json` lists it, this is `postgres_build.py` — meson and
MSVC on `windows-11-arm`, the shape `mariadb_build.py` already has, with vcpkg for the ICU, OpenSSL,
libxml2, lz4 and zstd the borrowed cells carry — and the row it has to match is not a matter of
taste: 15 provides and 46 extensions, which `parity.py` will check against the other five cells.

Two conditions before it starts, and they are cheap to re-ask. The buildfarm animal has to be green
on the branch, not merely past target 1206 — the last run on `REL_19_STABLE` failed in
`pg_amcheckCheck`. And EDB has to still not publish one, because a borrow beats a build here as
everywhere else.

#### Re-asked 2026-08-16: still shut, and one of the conditions was watching the wrong machine

**The release.** `versions.json` names 18 as the newest major and lists no 19 at all — 19 is at
**Beta 3**, released 2026-08-13, the same day as the five minors, with no RC yet and GA planned for
September. `series()` reads that document, so until it gains a 19 row there is nothing for a recipe
to offer. This is a wait of weeks, not of anything anybody here has to do.

**The borrow.** Still none: `postgresql-18.0-1-windows-arm64-binaries.zip` answers 403 where the
`windows-x64` name of the same version answers 200. A build is still the route.

**The buildfarm, which is the condition that needed correcting.** The two animals have names, and
writing them down is most of what makes this cheap to ask again — `unicorn` (approved 2025-12-12,
Windows 11 Pro 10.0.26100, MSVC 19.50.35718, arch `aarch64`) and `hoatzin` (2026-03-16, Windows 11,
msvc 19.50.35725, arch **`ARM`** — which is why a search of the member list for `arm64` finds only
one of the two).

The condition as written points at `unicorn`, and **`unicorn` is not a fair witness**. Its last green
run on any branch was 208 days ago; the 49 runs since have all failed, 44 of them at
`pg_amcheckCheck`, on `master` exactly as on `REL_19_STABLE`. And each takes 13 to 17 hours where
`hoatzin` does the same work in 45 minutes. A failure that behaves identically on every branch and
takes twenty times as long as the same platform needs is measuring the machine, not the branch.

`hoatzin` is what the platform actually looks like: **44 of 53 `master` runs green**, ~45 minutes
each, the newest 16 days ago. So Windows/ARM64 MSVC compiles PostgreSQL *and passes its whole test
suite* — a stronger statement than P7b could make, and the reason to expect 19 to work rather than
merely to hope it. `msvc_gendef.pl` accepting `aarch64` was the gate; on `master` it is open and
everything behind it is green too.

But `hoatzin` has never reported on `REL_19_STABLE`, or on any stable branch. So the condition as
written **cannot be met by evidence that exists** — not because 19 is broken there but because the
only animal reporting on 19 is the broken one. The question to re-ask is therefore not "is `unicorn`
green on 19" but **"is there a green `REL_19_STABLE` run from an animal that is also green on
`master`"** — `hoatzin` picking up the branch, or `unicorn` recovering. If 19 ships and neither has,
then the first green run of `postgres_build.py` is itself the evidence, and it costs one
`workflow_dispatch` to find out.

### [ ] P18b — Nothing says a server and a shell are installed as a pair

Both halves are published — [P18](roadmap-history.md) is the server on five lines, and
[P18a](roadmap-history.md) is `mongosh` 2.11.1 — and **neither archive mentions the other**. A
MongoDB artifact carries no shell and says nothing about where one comes from; the shell says nothing
about which server lines it speaks to. So `mix database open` on a MongoDB works only if a `mongosh`
happens to have been installed too, and nothing on either side arranges that.

This was named as a decision to make *before* publishing and it was not made; the shell was published
anyway, because it is useful to anyone who asks for it by name and the alternative was holding a
finished artifact for a decision in another repository. That is the whole of the debt: a pairing that
is obvious to a reader and invisible to the daemon.

**It is not this repository's alone, and possibly not this repository's at all.** The index has no
notion of one package implying another, and inventing one here — a `companions` field, say — would be
a schema change every kind pays for to serve one pair. The cheaper shape is MixEngine knowing that
opening a MongoDB means resolving a `mongosh`, the way it already resolves a PHP to run
`composer.phar` rather than the phar naming one. That is a question to settle over there before
anything is added here.

See [the design](superpowers/specs/2026-09-15-mongodb-packaging-design.md) and
[packages/mongodb.md](packages/mongodb.md#the-shell-is-a-different-package).

### [~] P22 — Meilisearch

The Community Edition binary on five cells, packed on demand from the newest release. `tools/meilisearch.py`
and `build-meilisearch.yml` are written, and the Windows x86_64 cell of 1.53.2 packs, indexes and
searches from a moved directory, and passes `parity.py` on a development machine. What is left is the
four Unix cells' floors, whether a Windows runner's administrator token matters, and the first release.

See [the design](superpowers/specs/2026-09-17-meilisearch-packaging-design.md) and
[packages/meilisearch.md](packages/meilisearch.md).

---

## Working on this file

- Tick the task here, and move it to [`roadmap-history.md`](roadmap-history.md) in the same commit,
  leaving one row in *What each task settled*. One file to work in and one to read back — not a
  phase per section, because this repository is one pipeline.
- New work goes **where it belongs in the order**, with the next free suffix on the task it follows
  (`P2a`, `P2b`) rather than at the end.
- A task with a design document behind it links to its spec under `docs/superpowers/specs/` rather
  than restating it here — see
  [`.claude/standards/plans-and-specs.md`](../.claude/standards/plans-and-specs.md).
- **One note, one place.** Why a recipe does what it does belongs in its docstring, beside the code
  it is about; what a packaging decision settled for one kind belongs on that kind's page in
  [`packages/`](packages/), and what it settled for the whole repository belongs beside the rule it
  is part of — [borrowing](borrow-before-you-build.md), [parity](one-version-means-one-thing.md),
  [layout](repack-do-not-rearrange.md), [dates](end-of-life-dates.md),
  [the archive](the-archive.md); what building something the hard way taught belongs in
  [`building-from-source.md`](building-from-source.md). [`../README.md`](../README.md) carries the
  table of what is packaged and links to all of it, and nothing else. What this file carries is only
  what none of those can: what has not been done yet, and what has to be decided before it can be.
