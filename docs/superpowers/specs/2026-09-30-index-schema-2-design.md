# Index schema 2: one signed root, one file per kind, and a publish that reads only what is new

*Design for an index that a client can still load quickly, and a pipeline that can still build it,
when it describes ten years of versions — without taking back the promise that no version is ever
removed.*

---

## Why this exists

The index is cumulative by promise. Two things grow with it, and neither survives ten years as it
is. Measured on the index generated 2026-09-30T04:29:22Z:

| | Today (measured) | In ~10 years (estimated) |
| --- | --- | --- |
| Packages / artifacts | 119 / 635 | ~3,100 / ~16,500 |
| `index.json` as published | 584 KB, 18,785 lines | ~16 MB |
| Archives the index names | 21.9 GiB | several hundred GiB |

The estimate is upstream patch cadence per kind (about 300 new packages a year across the 18 kinds
published today) times today's bytes per package. It is an estimate, not a measurement, and it
assumes no new kinds — which September alone disproved six times.

**The client** (`mixlab/crates/mixengine-core/src/index.rs`) downloads the document whole, verifies
it whole and parses it whole:

- it is fetched again every six hours, with no way to ask "did anything change";
- one 30-second timeout covers the whole request, so at 16 MB a connection slower than about
  4 Mbps can never fetch an index, and a fresh install on it can list nothing;
- every call re-reads, re-hashes and re-parses the whole cached file;
- GitHub serves a release asset as `application/octet-stream` with no `Content-Encoding`, whatever
  the request accepts (checked 2026-09-30), so none of this is hidden by gzip.

**The publisher** (`publish-index.yml`) downloads every asset of every release onto one runner, on
every run, to describe again what the published index already describes:

- 21.9 GiB today, about 188 MB a package; on the order of 80 GiB within a year, on a hosted runner
  whose disk is fixed;
- the tag list is asked for with `--limit 500`, and there are 121 releases today.

Where the index's bytes go says what to change in the format. Of 584 KB: 42% is indentation;
`provides`, `extensions` and `requires` are repeated verbatim across the cells of a package and
across the patches of a line; and every `url` follows one pattern with **no exception in 635
artifacts**.

## Decisions already made

| Question | Answer |
| --- | --- |
| Does the index stay cumulative? | **Yes.** Nothing here removes or hides a version. |
| How is it split? | **Every kind has its own file, and exactly one.** No kind is inlined for being small, and none is split further for being large. |
| How many signatures? | **One**, over a small root that names each kind file by sha256. |
| What are the files called? | `index-v2.json` and `index-v2-<kind>.json`. Permanent from the first MixEngine release that reads them. |
| Is a kind file deduplicated? | **Yes, with `shapes`.** `catalogue.py --decode` prints the schema 1 view for a person. |
| What happens to `index.json`? | It **stays published at schema 1**, at the same URL, written compact. It is generated until a date is chosen, and choosing one is not part of this. |
| Is the publisher's download fixed here? | **Yes, in this work**, not as a task of its own. |

## The documents

All of them are assets of the `index` release, beside `index.json`. Asset names are flat, so the
schema number is in the name: a schema 3 would need new names for the same reason this does.

```
index-v2.json            the root, signed
index-v2.json.minisig
index-v2-<kind>.json     one per kind, unsigned, named by hash in the root
```

Both documents follow the rule schema 1 already has: a field a client does not know is ignored, so
adding an optional one is not a schema change, and `schema` moves only for something a deployed
client cannot read.

### The root

```json
{
  "schema": 2,
  "generated_at": "2026-09-30T04:29:22Z",
  "base_url": "https://github.com/mixnz/mixengine-packages/releases/download",
  "kinds": {
    "node": { "sha256": "…", "size": 8747 },
    "php":  { "sha256": "…", "size": 30670 }
  }
}
```

- `generated_at` keeps the job it has today: it is what makes a rollback detectable.
- `kinds.<kind>.sha256` and `size` are of the kind file's exact bytes. This is what makes one
  signature enough: a kind file is believed only because a signed root names its hash, so an old
  `node` file cannot be served beside a new `php` one.
- A kind the root does not name does not exist. A kind, once named, is never dropped — the same
  promise as for a version, one level up, and `verify.py` holds it the same way.
- `base_url` is where artifacts live, stated once. A kind file's own location is **derived, not
  stated**: `index-v2-<kind>.json` beside the root, wherever the root was fetched from. So a mirror
  of the index is a copy of the `index` release, and a mirror of the artifacts changes one string
  before signing with its own key.

About 2 KB for 18 kinds, and about 100 bytes per kind added.

### A kind file

```json
{
  "schema": 2,
  "kind": "php",
  "shapes": [
    { "provides": { "php": "bin/php", "php-fpm": "bin/php-fpm" },
      "requires": { "glibc": "2.35" },
      "extension_dir": "ext",
      "extensions": { "static": ["…"], "shared": ["…"] } }
  ],
  "packages": [
    { "version": "8.5.11", "channel": "stable", "eol": "2029-12-31",
      "artifacts": [
        { "os": "linux", "arch": "x86_64", "format": "tar.zst",
          "sha256": "99463125…", "size": 53031154, "shape": 0 }
      ] }
  ]
}
```

Three changes from schema 1, and each is an encoding of the same facts rather than a new fact:

1. **`shapes`.** Everything about an artifact that is not its bytes — `provides`, `requires`,
   `extension_dir`, `extensions` — is written once in a table and referred to by position. It is
   still stated *per artifact*, which schema 1 insists on and is right about: a Windows PHP and a
   Linux PHP point at different shapes. What stops is writing the same 900 bytes for each of four
   Unix cells and again for every patch of the line. PHP needs 21 shapes for 85 artifacts; redis
   needs 4 for 98. Two shapes are the same shape when their values are equal, whatever order their
   keys were written in.
2. **No `url`.** It is composed:
   `{base_url}/{kind}-{version}/{kind}-{version}-{os}-{arch}.{format}`. `format` is `zip`, `tar.zst`
   or `tar.gz` — the one part of the name that cannot be derived, since Linux uses two. This turns
   "every URL is ours" from something `verify.py` checks into something the format cannot say
   otherwise, and it makes `mkindex.rebase` a one-line change to the root.
3. **Compact JSON, and no timestamp.** A kind file is a function of its packages and nothing else:
   packages in the generator's existing order, shapes in order of first use, keys sorted, no
   whitespace, one trailing newline. Two runs over the same releases produce the same bytes and so
   the same hash. That is what lets a PHP release leave the other seventeen files — and every
   client's copy of them — untouched.

`kind` is repeated inside the file so that a file saved under the wrong name says so. The hash in
the root is what is trusted; this is what is read by a person.

A kind file is not meant to be read top to bottom — an artifact says `"shape": 3`. For a person,
`python tools/catalogue.py --decode <kind file>` prints the schema 1 view of it.

### What it weighs

Every kind, encoded as above from the published index:

| | Schema 1 | Schema 2 |
| --- | --- | --- |
| Whole catalogue today | 584 KB, one file | 151 KB, 18 files + 2 KB root |
| Largest kind today (php, 17 versions) | 179 KB of the one file | 31 KB |
| Cost of one more version | 2–12 KB | 0.7–0.9 KB (almost all of it sha256) |
| Whole catalogue in ~10 years (estimate) | ~16 MB | ~2.5 MB across the kind files |
| Largest kind file in ~10 years (estimate) | — | a few hundred KB |

So one file per kind is enough on its own. Splitting a kind again into current and end-of-life
lines was considered and is not proposed: the largest file a client would ever fetch in ten years
is smaller than the whole index is today. Without `shapes` the same catalogue is 264 KB today, and
about twice the size for good.

What a client pays, by case:

| Case | Fetched |
| --- | --- |
| A six-hour check with nothing published | the signature, about 300 bytes |
| A check after a PHP release, on a machine that uses PHP | signature, root, `index-v2-php.json` |
| The same, on a machine that does not use PHP | signature and root |
| A first run | signature, root, and each kind as it is first asked for |
| Listing every kind at once | every kind file once — 151 KB today — and afterwards only the ones that changed |

## What a client must do

This is the contract; implementing it is a task in `mixlab`, with a design of its own.

1. **Ask for the signature first.** `GET index-v2.json.minisig`. If it is byte-identical to the
   cached one, nothing was published: the cache counts as fetched now and no document is requested.
   Every publish writes a new `generated_at`, so every publish has a new signature and none is
   missed. A server replaying an old signature only holds a client on the root it already has,
   which is what withholding the index does today.
2. **Otherwise fetch the root**, verify it against the signature *before* parsing, check `schema`,
   and refuse a `generated_at` older than the cached root's — all as today.
3. **Bring the kinds already cached up to the new root.** For each kind file in the cache whose
   hash differs from the new root's, fetch it, refuse it unless its length is exactly `size`, and
   check its sha256 *before* parsing. Only when every one of them checks out are the new root and
   the new kind files stored.
4. **If any of that fails, keep everything.** The old root and the old kind files stay, and the
   answer is `Stale`, exactly as a failed fetch is today.
5. **A kind not yet cached is fetched on first use**, against the cached root. A hash that does not
   match means the root is behind: refresh once and retry, then fail for that kind only.

The rule underneath 3–5 is one invariant: **every kind file in the cache hashes to what the cached
root says.** A cached kind file is re-checked against the cached, re-verified root whenever it is
read from disk, so the trust boundary stays where `index.rs` puts it today — nothing on disk is
believed because it was believed once.

A client is also expected to keep what it parsed in memory and re-read only when the cache changes.
That is not part of the format, and it is the other half of "loads quickly".

## Publishing: reading only what is new

The index is already built by merging into the published one; `mkindex.merge` carries every package
forward and replaces only the artifacts a run found. What is wasteful is *finding* all of them again.
A new `tools/gather.py` decides, before anything is downloaded, which versions have to be looked at.

### Deciding, from the listing alone

GitHub's release API states, for every asset, its `size` and a sha256 `digest`. One paginated
listing of every release — no limit — is therefore enough to compare against the published index.
Checked on 2026-09-30: all 635 artifacts in the index match the API's digest and size, and no asset
is without a digest.

For each release `<kind>-<version>`, taking only archives that have a `<archive>.json` beside them —
an asset without a manifest is not an artifact, as today:

| What the listing says | Verdict |
| --- | --- |
| Every archive is in the index with that sha256 and size, and the index names no other cell | **settled** — nothing is downloaded |
| The version is not in the index | **changed** |
| A cell was added, or an archive's digest or size differs from the index's | **changed** — and said out loud, since this is a published archive replaced |
| An asset has no digest | **changed** — what cannot be compared is looked at |
| The index names a cell the release no longer has | **settled, with a warning** — the merge keeps it, and `check-archive.yml` is what reports a deletion |

The digest is only ever a reason to look or not to look. Nothing from the listing is written into
the index: a settled artifact keeps the hash that was taken from its bytes when it was first
indexed, and a changed one is hashed again from the bytes downloaded.

### Looking, one version at a time

A **changed** version is downloaded whole — every cell, archive and manifest — because comparing
the cells of a version to each other is what `parity.py` is for. Then, per version:
`parity` on that directory, `mkindex.collect` on it, and the directory is deleted before the next
one. The disk a run needs is the largest single version, which is 0.92 GiB today (`java 25.0.4.1`),
whether the archive holds twenty gibibytes or six hundred.

`gather.py` writes what it found as one file, and `mkindex.py` merges that instead of reading a
directory of archives. Everything after the merge is unchanged.

### What this gives up, and how to get it back

Today every run re-reads every manifest and re-examines every archive, so a change to `parity.py`'s
rules, or a manifest corrected by hand without its archive changing, is picked up by the next run
without anyone asking. After this it is not. The workflow gets a `recheck` input — a kind, or `all`
— that treats those versions as changed. They are still processed one at a time, so `all` costs
time and not disk.

A run that starts from no published index at all — the 2026-08-17 case — is `all` by construction.

## Publishing: writing two encodings

`publish-index.yml` keeps its order: gather, generate, verify, sign, upload.

- **One model, two encodings.** `mkindex.py` builds the package list exactly as it does now — that
  list *is* schema 1 — and then writes it twice: `index.json`, and the schema 2 set through a new
  `tools/catalogue.py` holding `encode` and `decode`. `--previous` keeps reading `index.json`.
- **`index.json` is written compact.** Same document, same schema, 584 KB → 340 KB for every client
  that will never be updated. The workflow's `cat dist/index.json` becomes the summary line.
- **`verify.py` decodes what was encoded.** `decode(schema 2 set)` must equal the schema 1 package
  list, value for value. With that one comparison, every invariant already checked on schema 1 —
  nothing lost, no duplicate, the per-kind `provides` rules — holds for schema 2 without being
  written twice. It also checks each root entry against its file's bytes, both documents against
  their JSON Schemas, and that no kind in the published root is missing from the new one.
- **A URL that does not fit the pattern fails the run.** `encode` refuses an artifact whose schema 1
  `url` is not what the pattern composes, rather than publishing a schema 2 that points somewhere
  else than schema 1 does.
- **Two signatures**, same key, same step: `index.json` and `index-v2.json`.
- **Upload order, changed files only:** kind files whose hash differs from the published root's,
  then `index-v2.json`, then `index-v2.json.minisig` last. GitHub cannot replace several assets at
  once, so there is a window, and what a client can meet inside it is one of three things: the old
  signature (nothing changed, as far as it can tell), a root that does not verify against the
  signature beside it, or a kind file that does not hash to what its root says. The last two are
  refusals and end in `Stale` or a retry. None of them is a wrong answer.

`check-archive.yml` gains one question beside the two it asks weekly: is the published schema 2 set
whole — signature, every hash and size, and `decode` equal to the published `index.json`. That is
what notices an upload that stopped halfway and stayed that way.

## Rollout

Four steps, each publishable on its own and in this order, because the first two change nothing a
client can see and the second is the one with a deadline.

1. **`index.json` written compact.** Same document; every deployed client reads it as before.
2. **`gather.py`.** The index that comes out must be identical, package for package, to what the
   download-everything workflow produces on the same day — run both once and compare before the old
   step is removed.
3. **Schema 2 published beside schema 1.** Nothing reads it yet, so it can be regenerated or
   deleted freely. Run it for a few index publishes and compare.
4. **A MixEngine release reads schema 2.** From that release on the names and the format above are
   load-bearing in the way `index.json` is today. `index.json` goes on being generated.

## Scope

**In scope:** the two document formats and their JSON Schemas; `tools/catalogue.py` and
`tools/gather.py`; `mkindex.py`, `verify.py`; `publish-index.yml`; the extra check in
`check-archive.yml`; tests; and the documents that describe any of it.

**Out of scope:**

- **The client.** Its contract is above; its design belongs to `mixlab`.
- **`extensions.json` and the blueprint gallery.** Separate documents with their own growth.
- **`permanence.py` and `watch.py`.** They read `index.json`, which stays. They move to `decode`
  when `index.json` is retired, not before.
- **When `index.json` stops being generated.**
- **Compression.** A `.zst` beside each file would shrink them further, and would mean running a
  decompressor on bytes before they are verified. At these sizes it buys little.

## What changes

- **New:** `tools/catalogue.py`, `tools/gather.py`, `schema/index-v2.schema.json`,
  `schema/index-v2-kind.schema.json`, `tests/test_catalogue.py`, `tests/test_gather.py`.
- **Changed:** `tools/mkindex.py` (merges what `gather.py` found; writes both encodings),
  `tools/verify.py`, `.github/workflows/publish-index.yml` (the download loop and `--limit 500` go;
  `recheck` input), `.github/workflows/check-archive.yml`, `release/publish.sh` (it prints the
  URLs, and its header says every asset is downloaded).
- **Docs:** `docs/the-archive.md` — the `index` tag now holds one file per kind, still without
  accumulating, because a kind never leaves; and its paragraph on sidecars says the index is made
  from every manifest on every run, which stops being true. `release/README.md` and `README.md`
  where they describe the index or how it is published. The docstring of `parity.py`, which says
  where it runs.

## Tests

Stdlib only, like the rest.

`tests/test_catalogue.py`:

- `decode(encode(packages)) == packages`, on a fixture with a Windows/Unix PHP pair, a package with
  `requires` on one cell only, an artifact with no optional field at all, and a kind with a single
  version;
- two artifacts whose shapes differ only in key order share one shape;
- encoding twice gives identical bytes, and adding a version to one kind changes that kind's file
  and the root and nothing else;
- an artifact whose `url` does not fit the pattern is refused by `encode`;
- a root whose hash or size disagrees with its kind file, a `shape` that points past the table, and
  a new root missing a kind the published one names are each refused by `verify`.

`tests/test_gather.py`, against a listing and an index held in the test rather than the network:

- each row of the verdict table above, one test a row;
- an archive with no manifest beside it is ignored — `mysql-5.7.44-patched-src.tar.gz` is the real
  one;
- `recheck` with a kind marks that kind's versions changed and no other's; `all` marks every one;
- with no published index, every version is changed.
