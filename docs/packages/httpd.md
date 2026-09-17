# Apache httpd

*Part of [mixengine-packages](../../README.md), which holds the table of what is packaged.*

The web server that reads `.htaccess`, compiled on every cell because nothing publishable exists to
borrow:

| OS / arch | Range | How |
| --- | --- | --- |
| macOS aarch64, x86_64 | **2.4** | **built** from the ASF's source release |
| Linux x86_64, aarch64 | **2.4** | **built**, on Ubuntu 22.04 for the glibc floor |
| Windows x86_64, aarch64 | **2.4** | **built** with MSVC and upstream's CMake build |

The design, and what was measured before and during the recipe, is
[the spec](../superpowers/specs/2026-09-17-httpd-packaging-design.md).

## Why it is a row

The index already has nginx and Caddy, and neither reads `.htaccess`. A large share of the PHP this
index goes back to 7.0 to serve — WordPress, Drupal 7, older Laravel and CodeIgniter installs —
ships its routing in `.htaccess` and assumes `mod_rewrite`. Serving those through nginx means
translating the rules first, and a local development environment that has to translate a project's
configuration before the project runs is not doing its job.

## Why nothing is borrowed

The Apache Software Foundation publishes **source only**. On Windows the build everybody uses is
Apache Lounge's, and it fails every test a borrow here has to pass: the SHA and PGP are *sent by
mail on request*, one current build is kept with no statement that older ones stay, the same httpd
version is rebuilt under a date suffix (`httpd-2.4.68-260827-Win64-VS18.zip`) so one version number
is several programs, redistribution is not addressed either way, and there is no ARM64 build.

So all six cells are compiled, and `conf/`, `error/` and the twenty modules come from the same
tarball on every one of them.

## One version means one module set

With no borrowed build to read a specification off — nginx's row copies `nginx -V` from upstream's
own zip — the module set **is** the specification, and it is checked twice per cell: `modules/` is
compared against it before packing, and `httpd -M` after the tree has been moved.

Twenty modules, every one shared: `mime`, `dir`, `alias`, `rewrite`, `headers`, `expires`,
`deflate`, `filter`, `setenvif`, `env`, `log_config`, `vhost_alias`, `authz_core`, `authz_host`,
`access_compat`, `proxy`, `proxy_fcgi`, `ssl`, `socache_shmcb`, `http2`.

`mod_access_compat` is in it because `.htaccess` files written for 2.2 still say `Order allow,deny`,
and a project that fails on that line is the one this row exists for. `mod_filter` is in it because
`AddOutputFilterByType` — how everybody turns `mod_deflate` on — is mod_filter's directive in 2.4,
not mod_deflate's.

The MPM and the platform glue are **compiled into the server** rather than shipped as modules:
`event` with `mod_unixd` on Unix, `mpm_winnt` with `mod_win32` on Windows. That is httpd's
asymmetry, and keeping it out of `extensions` is what lets `parity.py` compare the twenty modules
the row decided on instead of reporting `unixd` as something five cells have and the sixth does not.

## How PHP reaches it

**Not through `mod_php`.** `php_windows.py` takes the non-thread-safe build on purpose and an
in-process Apache module needs the thread-safe one; on Unix `static-php-cli` builds no
`apache2handler`. So httpd reaches PHP the way nginx does: **`mod_proxy_fcgi` to `php-fpm` on Unix
and to `php-cgi` on Windows.**

One consequence a user will meet: **`php_value` and `php_flag` in `.htaccess` are `mod_php`
directives**, and under FastCGI httpd answers 500 to them. PHP's own answer is `.user.ini`.

## What is built into it

APR 1.7.6, APR-util 1.6.5, OpenSSL 3.5.7, PCRE2 10.47, zlib 1.3.2, nghttp2 1.70.0 and expat 2.8.4 —
every one from source against a pinned digest, and OpenSSL, PCRE2 and zlib are the same pins the
**nginx** row uses, so the two web servers of one index release carry the same TLS library.

On Unix they are static archives built with `-fPIC`, because each one ends up inside a shared module
(OpenSSL in `mod_ssl.so`, zlib in `mod_deflate.so`, nghttp2 in `mod_http2.so`, expat in
`libaprutil-1`), and the only shared libraries in the tree are APR's own. On Windows they are DLLs
beside `httpd.exe`, which is where the loader looks first — the same shape Apache Lounge ships — and
a DLL is kept only when the server or a module actually imports it.

## What ships, and what does not

`bin/httpd`, `modules/`, `conf/` (upstream's default configuration as a reference, and the
`mime.types` a rendered `TypesConfig` names), `error/`, APR's libraries on Unix and the DLLs on
Windows, and `licenses/`.

Removed after installation, with what each weighed on Linux x86_64: `manual/` (24.0 MB), `icons/`
(434 kB, read only by `mod_autoindex`, which is not in the set), `include/` (1.7 MB) and `build/`
(387 kB) with `bin/apxs`, `man/` (81 kB), the sample `htdocs/` and `cgi-bin/`, the static and import
libraries, and the fourteen support programs — `ab`, `htpasswd`, `htcacheclean` and the rest — that
no service recipe calls. What is left packs to **6.1 MB on Linux x86_64 and 5.6 MB on macOS
aarch64**.

## What is proven

From a directory the tree was moved to, with `-d <archive> -f <rendered conf>` and everything the
server writes pointed outside the archive: `httpd -v` names the release; `httpd -t` accepts a
configuration that uses a directive of every module, including `RewriteEngine` and a
`ProxyPassMatch` to an `fcgi://` address; `httpd -M` reports all twenty modules loaded from
`modules/`; the server starts and serves a static file; a path rewritten by an `.htaccess` that also
says `Order allow,deny` comes back gzip-compressed with the header `mod_headers` was told to set;
and the server stops — `httpd -k stop` on Unix, a console control event on Windows, where that flag
talks only to an installed service — after which the port refuses connections again.

**No PHP in it.** `mod_proxy_fcgi` is proved by the configuration test and by the module loading; a
test of this artifact that needed another kind could go red for a reason that is not this artifact.

## Requirements

`glibc` 2.34 on Linux, macOS 14.0 and 15.0 on the two macOS cells, and the **Visual C++ 2022
redistributable** on Windows, measured off the import tables of everything in the tree.

**No end-of-life dates.** The 2.4 line has no published schedule; `httpd` carries no `eol` field,
for the reason `tools/eol.py` states about every kind that has none.
