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

> **Amended 2026-09-18, and this is the sentence the measurement moved.** MSVC targets ARM64
> natively; httpd's own Windows build does not. Two things stop it, both of them 32-bit assumptions
> in the build rather than in the code, and both answered without touching a source file — see
> [what was measured](#what-was-measured).

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
- **Amended 2026-09-18**: `mod_filter` as well, which is twenty. `AddOutputFilterByType` — the only
  line most `.htaccess` files and most tutorials use to turn `mod_deflate` on — is **mod_filter's**
  directive in 2.4, not `mod_deflate`'s. The set had the compressor and not the thing that switches
  it on by content type, so a configuration nobody would think twice about would have been a 500.

**Every module is built shared**, so a rendered configuration turns each on or off, and `extensions`
in the manifest lists them the way PHP's shared extensions are listed.

**The platform asymmetries are httpd's, and declared rather than hidden**: the MPM is `event` with
`mod_unixd` on Unix and `mpm_winnt` on Windows. A module that exists only on one platform is not a
parity failure; one that is missing from one cell is.

**Amended 2026-09-18: those platform modules are compiled *into* the server and are not in
`extensions` at all**, which is what keeps `parity.py` — where `shared` counts for every kind but PHP
— comparing the twenty modules the row decided on rather than reporting `unixd` as something five
cells have and the sixth does not. Two measurements are behind that:

- **`--enable-modules=none` switches `mod_unixd` off with everything else**, and an httpd without it
  starts and then refuses every connection: `AH00136: Server MUST relinquish startup privileges
  before accepting connections`, on both macOS cells. It is asked for by name, static.
- **A module whose default is "whatever my parent is" follows `mod_proxy`**: enabling proxy built
  fourteen more — every `mod_proxy_*` protocol and every balancer — so `configure` is handed
  `--disable-<name>` for every module in its own list that this row did not choose.

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

## What was measured

*Amended 2026-09-18, from CI runs of the recipe on all six cells. The five questions above, in
order, and then what nobody had asked.*

**1. Windows on ARM64 builds, and needed three things named — none of them a source edit.** The
libraries were the easy half: zlib, PCRE2, expat, nghttp2 and OpenSSL (`VC-WIN64-ARM`, `no-asm`) all
build unpatched with the native ARM64 compiler. httpd's own Windows build is where the 32-bit
assumptions are.

- **APR and APR-util declare a CMake minimum below 3.5**, which CMake 4 — the version on the ARM
  runner's `PATH`, where the x64 runner offered Visual Studio's 3.x — refuses outright. Answered
  with `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`, CMake's own documented escape.
- **`os/win32/BaseAddr.ref` gives every DLL a 32-bit preferred load address**, and `link.exe`
  answers `LNK1355: invalid base address 0x6FF00000; ARM64 image cannot have base address below
  4GB` at the first link of `libhttpd.dll`. The **copy CMake generates in the build directory** has
  4 GB added to each address; upstream's file is untouched, the table keeps its spacing, and a
  preferred base is a request that ASLR overrides anyway.
- **OpenSSL installs `openssl/applink.c` only for its x86 and x64 targets**, and `support/ab.c`
  includes it whenever OpenSSL was found — so the ARM64 build stopped at `abs.exe`, after every
  module had linked. The file is copied out of OpenSSL's own source tree when the install did not
  leave one.

**2. What the removal list weighs**, on Linux x86_64: `manual/` 24.0 MB, `include/` 1.7 MB, the two
static APR archives 3.4 MB, `icons/` 434 kB, `build/` 387 kB with `apxs`, `man/` 81 kB, and fourteen
support programs of which `ab` alone is 7.1 MB. What is left packs to 6.1 MB on Linux x86_64 and
5.6 MB on macOS aarch64.

**3. The floors.** `glibc` 2.34 on Ubuntu 22.04, macOS 14.0 and 15.0 on the two macOS cells, and the
**Visual C++ 2022 redistributable** on Windows, from `vcruntime140.dll` in the import tables — the
dynamic CRT is deliberate, because httpd, APR and every module pass CRT-owned objects across DLL
boundaries.

**4. `mod_http2` is in**, and nghttp2 costs 156 kB of DLL on Windows; on Unix it is a static archive
inside `mod_http2.so`. Nothing about it needed a second round.

**5. A Windows runner's administrator token changed nothing**: the token is elevated on both Windows
runners and the server built, started, served and stopped the same either way.

**And what nobody had asked**, each of which cost a CI round:

- **`--enable-modules=none` also switches off `mod_unixd`**, and httpd then starts and refuses every
  connection with `AH00136`. Asked for by name, static, on both macOS cells before either Linux cell
  had got that far.
- **`mod_proxy` brings fourteen more modules**, because a module whose default is its parent's
  follows it; every module outside the set is now disabled by name.
- **Stripping has to happen before relocation, and on the install prefix**: `relocate.bundle` copies
  APR's libraries out of the prefix over the tree's, so a tree stripped first gets its debug
  information back — and a tree stripped *afterwards* has been through `patchelf`, whose rewritten
  segments `strip` then changes in a way `strip.debug` refuses to publish.
- **`httpd -k stop` is a Windows service command.** In a console it answers `AH00436: No installed
  service named "Apache2.4"` while the server it was aimed at goes on serving. What stops that one is
  a console control event, which is also what upstream's Windows documentation says.
- **`mod_deflate` does not compress a 28-byte body**, so the smoke test's file is 64 kB. A check
  that asserted gzip on one line would have been a red run about nothing.

## The task

**P23 — Apache httpd**: `tools/httpd.py` (Unix) and `tools/httpd_build.py` (Windows),
`tools/httpd_smoke.py`, `.github/workflows/build-httpd.yml`, `docs/packages/httpd.md`, a row in the
README table, and the absence in `eol.py`'s docstring.
