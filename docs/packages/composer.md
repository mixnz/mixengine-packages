# Composer, a phar published like a runtime

*Part of [mixengine-packages](../../README.md), which holds the table of what is packaged.*

Composer is one file, `composer.phar`, that a PHP runs. MixEngine installs it as a runtime kind of
its own (roadmap task T27c there), so it has to be in this index like one — and the index has no
cell for a file that runs everywhere.

| OS / arch | Range | How |
| --- | --- | --- |
| all six | **2.2 (LTS) and 2.x newest** | **borrowed** — `composer.phar` from the GitHub release, checked against getcomposer.org's `composer.phar.sha256sum` |

**Six archives of one payload.** `tools/composer.py` packs the same bytes once per target it runs
on, in the archive format that target takes — a zip on Windows, a `.tar.zst` elsewhere — because a
`kind`/`version` in the index is a list of `(os, arch)` artifacts and nothing else. A schema cell for
"any" would be the right shape the day a second OS-independent artifact exists; for one file, six
small uploads cost less than a schema bump every client has to learn.

**Checked against a second publisher, not a keyserver.** Composer signs releases with PGP; verifying
that means a keyserver, which is the moving dependency the Node.js and Caddy recipes refuse. The
project's own site publishes the SHA-256 of the same file over HTTPS, and that is what the download
is compared against before anything is packed.

**Proved by the PHP that runs it.** A phar starts nothing on its own, so the smoke test is
`php composer.phar --version` from a directory the file was moved to, under the runner's PHP
(pinned by `setup-php` in `build-composer.yml`), expecting the version being packed.

**Which line goes with which PHP** is Composer's rule and MixEngine's pin: 2.3 and later need PHP
7.2.5 or newer; a project on an older PHP pins `composer = "2.2"`. Nothing here encodes it, and the
`2.2` line is published so that the pin has something to resolve to.

No end-of-life dates: Composer states none, and `eol.py` has no table for it.
