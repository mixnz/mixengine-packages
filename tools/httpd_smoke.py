#!/usr/bin/env python3
"""Prove a moved httpd is a web server: every module loads, `.htaccess` is honoured, and it stops.

**Started the way MixEngine will start it, and only that way.** httpd compiles its prefix in, so
every invocation passes ``-d <archive root>`` and ``-f <rendered configuration>``; ``LoadModule``
lines and ``TypesConfig`` are relative to that root, and everything the server *writes* — the pid
file, the error log, the runtime directory for its mutexes and scoreboard — points into an instance
directory beside the archive, never into it. A check that let httpd write into its own tree would
pass on a runner and fail on a machine where the archive is read-only.

**No PHP.** ``ProxyPassMatch`` to an ``fcgi://`` address is proved by the configuration test and by
``mod_proxy_fcgi`` loading, not by a live PHP — a test of this artifact that needs another kind can
go red for a reason that is not this artifact, which MongoDB's smoke test already wrote down.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import gzip
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import httpd  # noqa: E402
import nginx  # noqa: E402
import relocate  # noqa: E402

STATIC = "static.txt"

# What `OpenEvent` needs to be allowed to do to the shutdown event. See :func:`halt`.
EVENT_MODIFY_STATE = 0x0002

# **Large enough for `mod_deflate` to bother**, which a one-line file is not: the Windows cell
# served 28 bytes of `text/plain` uncompressed to a request that asked for gzip, and mod_deflate is
# right — it holds data back until it has a full buffer, and a body that ends before that comes out
# as it went in. So the file is 64 kB of one repeated line, which also makes the check on the
# decompressed body mean something.
BODY = "mixengine httpd static body\n" * 2048


def tell(program: Path, *args: str, path: str, timeout: int = 120) -> str:
    """Both streams of one httpd invocation, refusing a non-zero exit. httpd reports on stderr."""
    environment = dict(os.environ) | {"PATH": path}
    result = subprocess.run([str(program), *args], capture_output=True, text=True,
                            timeout=timeout, env=environment)
    said = f"{result.stdout}{result.stderr}".strip()
    if result.returncode != 0:
        raise SystemExit(f"httpd {' '.join(args)} exited {result.returncode}\n{said}")
    return said


def configuration(instance: Path, port: int) -> str:
    """A configuration in the shape MixEngine will render one, exercising every module it loads.

    Paths are quoted and written with forward slashes on every platform: :func:`borrow.moved` puts
    the archive under a directory whose name contains a space, and httpd on Windows reads forward
    slashes as it reads backslashes.
    """
    loads = "".join(
        f"LoadModule {name}_module {httpd.EXTENSION_DIR}/mod_{name}.so\n" for name in httpd.MODULES
    )
    documents = (instance / "htdocs").as_posix()
    logs = (instance / "logs").as_posix()
    return (
        f"{loads}"
        f"ServerName 127.0.0.1\n"
        f"Listen 127.0.0.1:{port}\n"
        f"PidFile \"{logs}/httpd.pid\"\n"
        f"DefaultRuntimeDir \"{logs}\"\n"
        f"ErrorLog \"{logs}/error.log\"\n"
        f"LogLevel info\n"
        f"TypesConfig conf/mime.types\n"
        f"LogFormat \"%h %l %u %t \\\"%r\\\" %>s %b\" common\n"
        f"CustomLog \"{logs}/access.log\" common\n"
        f"Protocols h2c http/1.1\n"
        f"SSLProtocol all -SSLv3\n"
        f"SSLSessionCache \"shmcb:{logs}/ssl_scache(512000)\"\n"
        f"AddOutputFilterByType DEFLATE text/plain\n"
        f"Header always set X-MixEngine \"smoke\"\n"
        f"ExpiresActive On\n"
        f"SetEnvIf Request_URI \"^/\" mixengine_smoke=1\n"
        f"SetEnv MIXENGINE_SMOKE 1\n"
        f"Alias /aliased \"{documents}\"\n"
        f"<Location /aliased>\n"
        f"    Require local\n"
        f"</Location>\n"
        # On a port nothing listens on, so it parses without becoming the default server.
        f"<VirtualHost 127.0.0.1:1>\n"
        f"    VirtualDocumentRoot \"{documents}/%0\"\n"
        f"</VirtualHost>\n"
        f"DocumentRoot \"{documents}\"\n"
        f"DirectoryIndex index.html\n"
        f"<Directory \"{documents}\">\n"
        f"    AllowOverride All\n"
        f"    Require all granted\n"
        f"</Directory>\n"
        f"ProxyPassMatch \"^/(.*\\.php)$\" \"fcgi://127.0.0.1:9/app/$1\"\n"
    )


def request(port: int, route: str, gzipped: bool = False, timeout: float = 5) -> tuple[str, dict]:
    headers = {"Accept-Encoding": "gzip"} if gzipped else {}
    call = urllib.request.Request(f"http://127.0.0.1:{port}{route}", headers=headers)
    with urllib.request.urlopen(call, timeout=timeout) as response:
        raw = response.read()
        answered = {name.lower(): value for name, value in response.getheaders()}
    if answered.get("content-encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace"), answered


def await_body(port: int, process: subprocess.Popen, log: Path, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    last = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"httpd exited {process.returncode} before it answered\n{read(log)}")
        try:
            body, _ = request(port, f"/{STATIC}", timeout=2)
            if body == BODY:
                return
            last = body
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as refusal:
            last = str(refusal)
        time.sleep(0.3)
    raise SystemExit(f"127.0.0.1:{port} answered {last!r}, expected the static file\n{read(log)}")


def halt(program: Path, invocation: list[str], process: subprocess.Popen, path: str) -> str:
    """Stop the server the way its platform stops one, and answer with what was done.

    **Two ways, and the Windows one took two measurements to find.** On Unix ``httpd -k stop`` reads
    the ``PidFile`` and signals the process it names, which is what a supervisor does.

    On Windows that same flag goes looking for a *service* — ``AH00436: No installed service named
    "Apache2.4"``, while the server it was aimed at went on serving — and the console events are no
    better: ``mpm_winnt``'s handler reads Control-Break as a **restart**, which is what the log
    showed (the workers exited and a new child started), and Control-C is disabled by default in a
    process group created with ``CREATE_NEW_PROCESS_GROUP``, which is the only kind a signal can be
    aimed at.

    What is left is the mechanism httpd itself uses: the parent creates an event named
    ``ap<its pid>_shutdown`` and ``ap_signal_parent`` opens that event by name and sets it. So this
    opens the same event and sets it, which is a graceful shutdown asked for in upstream's own words
    rather than a process killed from outside — and it is what a daemon supervising httpd on Windows
    will have to do.
    """
    if sys.platform != "win32":
        tell(program, *invocation, "-k", "stop", path=path)
        return "httpd -k stop"

    import ctypes  # Windows only, and only here

    name = f"ap{process.pid}_shutdown"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Declared, because the default return type is a C `int` and a HANDLE is a pointer: a truncated
    # one is a handle that fails to close rather than one that fails to open, which is worse.
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.OpenEventW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.SetEvent.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, 0, name)
    if not handle:
        raise SystemExit(
            f"the running server has no {name} event to open "
            f"({ctypes.FormatError(ctypes.get_last_error()).strip()}); mpm_winnt names its "
            f"shutdown event after the parent's pid and that is how it is stopped"
        )
    try:
        if not kernel32.SetEvent(handle):
            raise SystemExit(f"SetEvent on {name} failed: "
                             f"{ctypes.FormatError(ctypes.get_last_error()).strip()}")
    finally:
        kernel32.CloseHandle(handle)
    return f"the {name} event set, as httpd's own ap_signal_parent does"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else f"(no {path.name})"


def smoke(tree: Path, version: str, manifest: dict) -> dict:
    elsewhere = borrow.moved(tree)
    problems = relocate.verify(elsewhere)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        raise SystemExit("the relocated tree reaches outside itself")

    program = elsewhere / manifest["provides"]["httpd"]
    path = borrow.clean_path(program.parent)

    banner = tell(program, "-v", path=path)
    if f"Apache/{version} " not in banner:
        raise SystemExit(f"httpd -v says {banner.splitlines()[0]!r}, expected Apache/{version}")
    print(banner.splitlines()[0])

    instance = elsewhere.parent.parent / "instance"
    for directory in ("conf", "logs", "htdocs"):
        (instance / directory).mkdir(parents=True, exist_ok=True)
    documents = instance / "htdocs"
    (documents / STATIC).write_text(BODY, encoding="utf-8", newline="\n")
    (documents / ".htaccess").write_text(
        "Order allow,deny\n"
        "Allow from all\n"
        "RewriteEngine On\n"
        f"RewriteRule ^pretty$ {STATIC} [L]\n",
        encoding="utf-8", newline="\n",
    )
    port = nginx.free_port()
    config = instance / "conf" / "httpd.conf"
    config.write_text(configuration(instance, port), encoding="utf-8", newline="\n")
    invocation = ["-d", str(elsewhere), "-f", str(config)]

    print(tell(program, *invocation, "-t", path=path))
    print("httpd -t: accepted RewriteEngine, ProxyPassMatch to fcgi://, and every module's directives")

    listed = tell(program, *invocation, "-M", path=path)
    loaded = sorted(set(re.findall(r"^\s*(\w+)_module \(shared\)", listed, re.MULTILINE)))
    if loaded != sorted(httpd.MODULES):
        raise SystemExit(
            f"httpd -M loaded {', '.join(loaded)}; the row's modules are {', '.join(httpd.MODULES)}"
        )
    print(f"httpd -M: {len(loaded)} shared modules loaded from {httpd.EXTENSION_DIR}/")

    log = instance / "logs" / "error.log"
    console = instance / "logs" / "console.log"
    environment = dict(os.environ) | {"PATH": path}
    windows = sys.platform == "win32"
    foreground = [] if windows else ["-D", "FOREGROUND"]
    with console.open("wb") as sink:
        process = subprocess.Popen(
            [str(program), *invocation, *foreground], stdout=sink, stderr=subprocess.STDOUT,
            env=environment, cwd=str(instance),
            # **A process group of its own, because that is how Windows stops this server.** See
            # `halt`: the signal goes to the group, and without this flag it would go to the whole
            # console — this Python included.
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0,
        )
    try:
        await_body(port, process, log)
        print(f"GET /{STATIC}: served")

        body, headers = request(port, "/pretty", gzipped=True)
        if body != BODY:
            raise SystemExit(f"GET /pretty answered {body!r}; the .htaccess rewrite did not apply")
        if headers.get("content-encoding") != "gzip":
            raise SystemExit(f"GET /pretty was not deflated: {headers}")
        if headers.get("x-mixengine") != "smoke":
            raise SystemExit(f"GET /pretty carries no X-MixEngine header: {headers}")
        print("GET /pretty: rewritten by .htaccess under Order allow,deny, deflated, header set")

        stopped = halt(program, invocation, process, path)
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            raise SystemExit(f"{stopped} returned and the server was still running\n{read(log)}") \
                from None
        print(f"{stopped}: the server exited {process.returncode}")
        try:
            request(port, f"/{STATIC}", timeout=2)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            print(f"127.0.0.1:{port} refuses connections again")
        else:
            raise SystemExit(f"the parent exited and something is still serving on {port}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)

    started = read(log)
    openssl = re.search(r"OpenSSL/([\w.]+)", started)
    if not openssl:
        raise SystemExit(f"the error log names no OpenSSL although mod_ssl was loaded\n{started}")

    borrow.discard(elsewhere)
    return {
        "relocated": True,
        "openssl": f"OpenSSL {openssl.group(1)}",
        "loaded_extensions": loaded,
        "ran": [
            f"{manifest['provides']['httpd']} -v",
            "httpd -d <archive> -f <rendered conf> -t, with RewriteEngine, ProxyPassMatch to fcgi:// "
            "and a directive of every module",
            f"httpd -M, all {len(loaded)} shared modules loaded",
            "the server started, a static file served",
            "a path rewritten by .htaccess under Order allow,deny, deflated, with a header set",
            f"{stopped}, the server exited and the port refuses connections again",
        ],
    }
