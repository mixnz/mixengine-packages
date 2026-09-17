# Apache httpd, and the borrow that does not survive being checked

*Design for a proposed **P23**. It settles why no cell is borrowed, which modules one version means,
how PHP reaches it, and what the artifact promises. The rendered `httpd.conf`, virtual hosts and the
FastCGI wiring are MixEngine's.*

---

## Why this row exists at all

The index has two web servers, nginx and Caddy, and neither reads `.htaccess`. A large share of the PHP
this index goes back to 7.0 to serve — WordPress, Drupal 7, older Laravel and CodeIgniter installs —
ships its routing in `.htaccess` and assumes `mod_rewrite`. Serving those through nginx means
translating the rules, and a local development environment that has to translate a project's
configuration before the project runs is not doing its job.

This is also the **most expensive** of the five proposals written on 2026-09-17, because every cell is
built. It is written down anyway, because the alternative is that the cheapest-looking route — Apache
Lounge on Windows — gets taken without being checked.

What the row does **not** have behind it is blueprint demand, and this document does not claim any.

## What is offered

One line, every cell built here:

| Version | macOS aarch64 | macOS x86_64 | Linux x86_64 | Linux aarch64 | Windows x86_64 | Windows aarch64 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **2.4** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**2.4 is the only line**: the Apache HTTP Server Project maintains one, and 2.2 has been dead since
2017. `downloads.apache.org/httpd/` offers `httpd-2.4.68` on 2026-09-17, with `.sha256`, `.sha512` and
`.asc` beside it, and `archive.apache.org` keeps every earlier release — so versions and digests come
from the publisher, and nothing a blueprint pins is ever pruned upstream.

**Windows on ARM is a cell nginx's row does not have**, because nginx's Windows cell is a borrow of a
32-bit build and httpd's is compiled with MSVC, which targets ARM64 natively.

## Why nothing is borrowed

The Apache Software Foundation publishes source only. On Windows, the build everybody uses is
**Apache Lounge**'s, and it was evaluated on 2026-09-17 against what a borrow in this repository has to
be:

| A borrow needs | Apache Lounge offers |
| --- | --- |
| a digest from a publisher document, checked before packing | SHA and PGP **on request by mail**: *"Mail for the PGP signatures and/or SHA checksums"* |
| an archive that can be fetched again for the version it names | one current build, `httpd-2.4.68-260827-Win64-VS18.zip`; no statement that older builds stay |
| one build per version | a **date suffix** (`-260827`): the same httpd version is rebuilt against newer dependencies, so `2.4.68` is several different programs over time |
| a stated right to redistribute | no statement either way |
| Windows ARM64 | Win64 and Win32 only |

Every one of those is a reason on its own. Together they make it the nginx-on-Windows problem without
nginx's excuse: nginx's borrowed zip is at least upstream's, and frozen. So httpd is **built on all six
cells**, and there is no borrowed build to act as the specification the way nginx's `nginx -V` does —
which means the specification has to be written down, below.

## Where each cell comes from

- **Source**: `httpd-2.4.x.tar.gz`, checked against its `.sha512`; APR and APR-util from
  `downloads.apache.org/apr/`, checked the same way.
- **Dependencies**: the pinned OpenSSL, PCRE2 and zlib that `nginx.py` already declares and verifies
  (OpenSSL 3.5.7, PCRE2 10.47, zlib 1.3.2), plus nghttp2 for `mod_http2` and expat for APR-util. Using
  nginx's pins rather than a second set means the two web servers of one index release carry the same
  OpenSSL.
- **Unix, four cells**: `configure` with the bundled APR, the shape `nginx.py` has on its four compiled
  cells, then `relocate` as usual.
- **Windows, both architectures**: httpd and APR ship `CMakeLists.txt` for Windows; built with MSVC on
  `windows-2022` and `windows-11-arm`, the shape `mariadb_build.py` already has.

## One version means one module set

With no borrowed build to copy, the module set is chosen **once, here**, and `parity.py` checks every
cell against it:

- **Serving**: `mod_mime`, `mod_dir`, `mod_alias`, `mod_rewrite`, `mod_headers`, `mod_expires`,
  `mod_deflate`, `mod_setenvif`, `mod_env`, `mod_log_config`, `mod_vhost_alias`.
- **Access**: `mod_authz_core`, `mod_authz_host`, `mod_access_compat` — the last because `.htaccess`
  files written for 2.2 still say `Order allow,deny`, and a project that fails on that line is the one
  this row exists for.
- **PHP and TLS**: `mod_proxy`, `mod_proxy_fcgi`, `mod_ssl`, `mod_socache_shmcb`, `mod_http2`.

**Every module is built shared**, so a rendered configuration turns each on or off, and `extensions`
in the manifest lists them the way PHP's shared extensions are listed.

**The platform asymmetries are httpd's, and declared rather than hidden**: the MPM is `event` with
`mod_unixd` on Unix and `mpm_winnt` on Windows. A module that exists only on one platform is not a
parity failure; one that is missing from one cell is.

## How PHP reaches it

**Not through `mod_php`.** `php_windows.py` takes the non-thread-safe build on purpose, and the
thread-safe build is what an in-process Apache module needs; on Unix, `static-php-cli` builds no
`apache2handler`. So there is no `mod_php` on any cell, and httpd reaches PHP the way nginx does:
**`mod_proxy_fcgi` to `php-fpm` on Unix and to `php-cgi` on Windows.**

That has one consequence a user will meet and that should be said before they do: **`php_value` and
`php_flag` lines in `.htaccess` are `mod_php` directives**, and under FastCGI httpd refuses them with a
500. PHP's own answer is `.user.ini`. MixEngine's side decides whether to warn about it.

## What the rule takes out

A `make install` tree carries a great deal nothing running reads. Expected to go, with sizes measured
before the list is final: `manual/` (the documentation, in several languages), `build/` and `include/`
and `bin/apxs` (for compiling third-party modules, which needs the build tree and Perl), `man/`, the
sample `htdocs/` and `cgi-bin/`, and `bin/` utilities no service recipe calls. `error/` stays, because
the default configuration includes it; `icons/` goes with `mod_autoindex`, which is not in the set.

## What the artifact promises

```
kind        "httpd"
provides    { "httpd": "bin/httpd[.exe]" }
source      "built"
upstream    { url, sha256 (from the .sha512 beside the tarball), project: "apache/httpd" }
extension_dir  "modules"
extensions  { shared: [ the module set above ] }
requires    glibc     Linux, measured
            macos     measured
            vcredist  Windows, measured off httpd.exe and libapr-1.dll
smoke       { relocated: true, ran: [...] }
```

- **httpd compiles its prefix in.** Every start passes `-d <archive root>` and `-f <rendered conf>`, and
  `LoadModule` lines are relative to that root. That is how the smoke test starts it, which is what
  proves it rather than this sentence.
- **`conf/` holds upstream's default configuration**, kept as a reference and not used: MixEngine
  renders its own.

## Licence

Apache-2.0 for httpd, APR and APR-util; OpenSSL 3 is Apache-2.0; PCRE2 BSD; nghttp2 and expat MIT;
zlib its own. Every licence travels in `LICENSES.md`, collected the way `nginx.py` collects them.

## No end-of-life dates, on purpose

One line, no published schedule. `httpd` has no `eol` field.

## How it is proven

1. Move the tree somewhere unrelated.
2. `httpd -v` answers the manifest's version; `httpd -M` with a configuration that loads every module
   lists every module in `extensions.shared`.
3. `httpd -t` accepts a minimal configuration that uses `RewriteEngine`, a `ProxyPassMatch` to an
   `fcgi://` address and an `.htaccess` with `Order allow,deny`.
4. Start on a free port, `GET` a static file, `GET` a path an `.htaccess` rewrites, stop, confirm the
   process is gone.

**No PHP in the smoke test.** `ProxyPassMatch` is proved by the configuration test and the module
loading, not by a live PHP — the lesson MongoDB's smoke test already wrote down: a test of this
artifact that needs another kind can go red for a reason that is not this artifact.

## What this does not do

- **No `mod_php`**, on any cell, for the reasons above.
- **No borrowed Windows build**, for the reasons above.
- **No `apxs`, no headers**, so no third-party modules compiled against this tree.
- **No `mod_security`, `mod_fcgid`, `mod_jk`** or anything outside the httpd tarball.
- **Nothing in MixEngine.**

## What is left to measure before a line of the recipe is written

1. Whether httpd 2.4.68 and APR-util's CMake builds complete on `windows-11-arm` with nothing patched —
   the one leg with no precedent anywhere, and the first thing to run.
2. The size of everything on the removal list, per cell.
3. `vcredist` from the import tables, the glibc floor and the macOS floor.
4. Whether `mod_http2` is worth nghttp2 as a fourth bundled library, or waits.
5. Whether a Windows runner's administrator token matters (P12a).

## The task

**P23 — Apache httpd**: `tools/httpd.py` (Unix) and `tools/httpd_build.py` (Windows),
`tools/httpd_smoke.py`, `.github/workflows/build-httpd.yml`, `docs/packages/httpd.md`, a row in the
README table, and the absence in `eol.py`'s docstring.
