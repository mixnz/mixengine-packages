# Watching upstream, so a version is never missed

*Design for a scheduled job that notices a new patch of a line already packaged, builds it, and
publishes the index — for every kind, without a person remembering to look.*

---

## Why this exists

[`release/README.md`](../../../release/README.md) says it plainly: *nothing tells you a new version
exists*. `check-eol.yml` and `check-archive.yml` both watch something already published going wrong;
neither watches for something new appearing. The cost showed on 2026-09-30: the index still said PHP
8.3.33, 8.4.24 and 8.5.9 while php.net had 8.3.35, 8.4.26 and 8.5.11 — and 8.3.34, 8.4.25 and
8.5.10 were never packaged at all, because `build.sh php 8.4` builds the newest patch only. A
blueprint pinning one of those versions cannot be satisfied, and nothing in the repository knows.

## Decisions already made

| Question | Answer |
| --- | --- |
| How far does automation go? | **Build and publish.** A new patch goes all the way to the signed index with nobody involved. |
| Which versions? | **Every patch upstream published after the watch began** (2026-09-29), per line. No back-fill of history before that. |
| How often? | **Daily.** |

## Scope

**In scope:** a new *patch* of a *line that already exists in the index*, for every kind whose
recipe can build an exact version on request.

**Out of scope, reported rather than published:**

- **A new line** (PHP 8.6, Node 26, PostgreSQL 19). It needs a README row, `eol.py --update`, and
  possibly a written reason for an empty cell — the steps in "A new line" of `release/README.md`.
  The watcher lists it in the report and builds its newest version once without a release (step 4
  below); a person does the rest.
- **`meilisearch`.** Packed on demand, never back-filled, by its own design.
- **Versions older than what a line had when the watch began.** That is back-fill, and was decided against.

## How it works

One new workflow, `watch-upstream.yml`, on `schedule` (daily) and `workflow_dispatch` (with a
`dry` input that plans and reports without dispatching anything).

```
tools/watch.py --plan  ──►  plan.json  ──►  dispatch build-<kind>.yml per exact version
                                              │  (bounded concurrency, wait for each)
                                              ▼
                                  any build succeeded? ──► dispatch publish-index.yml publish=true
                                              │
                                              ▼
                              open / update one "upstream watch" issue with the report
```

### 1. `tools/watch.py` — deciding what is missing

Stdlib only, like every tool here. For each kind:

1. **Lines** = the lines present in the published `index.json`, computed with the same line logic
   `tools/eol.py` already uses (`eol.lines`), so "a line" means one thing in the repository.
2. **Upstream** = every stable version of each of those lines, asked from the source the kind's
   recipe already resolves against. The query is **imported from the recipe**, not rewritten: each
   `tools/<kind>.py` gets (or already has) a function `upstream_versions() -> list[str]`, so the
   watcher and the builder cannot disagree about what upstream said.
3. **Missing** = upstream versions of a line that are *newer than the line's floor*, are not in the
   index, and have **no release tag** `<kind>-<version>` yet. The **floor** is the newest version the
   line had before the watch began (`WATCH_SINCE`, read off each release's creation date), or the
   oldest version of a line first packed after it.
   - Not "newer than the newest in the index": that was the first rule, and on its first real run
     it dropped PHP 8.4.25 for good — its Windows leg failed the day 8.4.26 succeeded, and from then
     on 8.4.25 was "older than the newest" and never looked at again, nor reported.
   - A tag that exists but is not in the index is not rebuilt — it only makes the run publish the
     index. This is what keeps the watcher from ever clobbering a published tag
     ([`docs/the-archive.md`](../../the-archive.md)).
4. **New lines** = upstream lines newer than the newest line in the index, reported — and each is
   **built once without a release** at its newest version (`release=false`, so nothing is uploaded
   and the index is not published for it). The report says whether it built and which legs failed:
   on the first real run, Node 26 would have said "Linux: libatomic" a day before anyone looked.
   Found again by its `(no release)` run name, so a version is tried once; a newer patch of the line
   is tried afresh. Node's odd lines are not reported at all.

Output is `plan.json`: `{kind: [exact versions]}`, plus `new_lines` and `skipped`.

### 2. Always dispatch an exact version, never a line

`build-php.yml` with `branch=8.4` resolves the newest patch **independently on each leg** — Windows
against windows.php.net's `releases.json`, the others against php.net. windows.php.net routinely
lags php.net by a few days, so a line dispatch on release day would put the Windows cell of 8.4.25
under the old tag `php-8.4.24` and **clobber a published release**. Dispatching `8.4.26` instead makes
the Windows leg fail with "not found", no release is created, and the next day's run tries again.

The same rule covers every kind: the watcher passes exact versions only. The three list kinds
(`mariadb`, `mysql`, `postgres`) get **one run per version** — a list of one — so a run's name names
exactly one version and the failure count in section 5 is per version.

### 3. Knowing which run is which

`gh workflow run` returns no run id, and `_dispatch.sh` identifies a run by watching the listing
change — which races when several are dispatched at once. Every `build-*.yml` gets a `run-name`
carrying its input, for example:

```yaml
run-name: build php ${{ inputs.branch }}${{ !inputs.release && ' (no release)' || '' }}
```

The watcher finds its run by that name. This also makes the Actions list readable for people.

### 4. Concurrency and time

- At most **4 build runs at once**; the rest queue in the watcher. PHP alone is 5 legs, so this
  already keeps ~20 runners busy.
- The watcher job waits on its builds. GitHub caps a job at 6 hours; the slowest leg today is PHP's
  legacy compile at 180 minutes, and the watcher only ever builds *current* lines, which are the
  fast recipes. A build still running at the cap is left running and picked up by the next day's
  plan as "tag exists, publish the index".
- `concurrency: watch-upstream` so two watcher runs never overlap.

### 5. Failure

- A build whose any leg fails creates **no release** (that is already how every `release` job
  works: `!failure()`), so nothing half-built is ever published.
- `publish-index.yml` is dispatched when **at least one** build succeeded or a tag was found that the
  index lacks. The index is rebuilt from every release there is, so a failure elsewhere costs nothing
  but that one version.
- **Retry is the next day's run**, with no state kept: a version that failed is still missing. To stop
  a version that will never build from burning minutes daily, the watcher skips a version whose
  build run (found by `run-name`) has **failed 3 times**, and lists it under "needs a person".
- A failure only upstream can fix would hold the issue open for good, so a person can set the version
  aside in `data/watch-ignore.json` with a reason and an `until` date. Until then it is neither
  built nor reported; after it, it is built again and only failures from that day on count, in case
  upstream fixed it. MySQL 8.0.45, published with unsigned Linux tarballs, is the first.
- The report goes to **one** GitHub issue labelled `upstream-watch`, edited in place rather than a
  new issue per day: what was built, what failed with its run link, what is skipped, and which new
  lines exist. The issue is closed automatically by a run with nothing to say.

### 6. Permissions

`GITHUB_TOKEN` is allowed to trigger `workflow_dispatch`, so no PAT is needed:

```yaml
permissions:
  actions: write   # dispatch build-*.yml and publish-index.yml
  contents: read   # read releases
  issues: write    # the report
```

Signing stays exactly where it is — inside `publish-index.yml`, with the secrets it already has.

## Per-kind work

Each recipe must answer two questions for the watcher. Most already can; which ones cannot is the
first task of the plan, not a guess made here.

| Kind | Upstream source (already in the recipe) | Line | To verify |
| --- | --- | --- | --- |
| php | php.net `releases/index.php?json` | 8.4 | Windows leg accepts an exact version in `archives/` (it does: `resolve`) |
| node | nodejs.org/dist | 22 | — |
| python | python-build-standalone releases | 3.14 | an older patch may need an older release tag of the builder |
| ruby | cache.ruby-lang.org index.txt, rubyinstaller2 | 3.4 | Windows lags upstream like PHP |
| go | go.dev/dl `?mode=json&include=all` | 1.27 | — |
| java | api.adoptium.net, Microsoft build | 21 | version shape `21.0.12.1` |
| caddy, meilisearch, composer, mongosh | GitHub releases | 2.11 … | composer has an LTS line (2.2) beside current |
| nginx | nginx.org/download | 1.30 | stable vs mainline are both lines |
| httpd | downloads/archive.apache.org | 2.4 | — |
| redis, valkey | `*-hashes` README | 8.10 | — |
| memcached | GitHub tags | 1.6 | — |
| mongodb | downloads.mongodb.org `full.json` | 8.0 | — |
| mariadb, mysql, postgres | REST API / archives / `versions.json` | 11.8, 8.4, 17 | the `versions` list accepts **exact** versions, not only series |

## What changes

- **New:** `.github/workflows/watch-upstream.yml`, `tools/watch.py`.
- **Changed:** each `tools/<kind>.py` exposes `upstream_versions()` where it does not already;
  each `build-*.yml` gets a `run-name`.
- **Docs:** `release/README.md` — "Nothing tells you a new version exists" is replaced by what the
  watcher does and how to read its issue; `docs/adding-a-version.md` if it repeats the claim.

## Open questions

1. **Report channel.** The spec uses one GitHub issue. Anything else (email, a Slack webhook) needs a
   secret and is not proposed.
2. **Concurrency cap of 4.** Chosen to leave runners for manual work; the account's real runner
   limit decides whether it can be higher.
