#!/usr/bin/env python3
"""Start the MongoDB in an archive, ask it a question, and stop it.

**``mongod --version`` passes on an artifact MixEngine cannot use.** A service is packed to be run,
configured, watched and stopped, and each of those is something MixEngine's recipe will do through a
specific mechanism: a rendered ``mongod.conf``, a data directory made once before the first start, a
health check, and a shutdown. So this does all four, against the tree, from a directory it was moved
to.

**The question is spoken over the wire rather than through a shell.** From 6.0 the server archive
contains no shell at all, and ``mongosh`` is a different package on a different release clock — a
server smoke test that needs it is one that can go red for a reason that has nothing to do with the
artifact being tested, and on the day ``mongosh`` has no build for a cell, the server for that cell
would become unprovable. What is sent instead is an ``OP_MSG`` carrying ``{hello: 1}``, which is the
first thing every driver sends and is answered before any authentication is configured.

**The data directory is the point, not a detail.** ``mongod`` will not start without one and does
not create its own, which is the ritual MixEngine's recipe has to own — the same shape MariaDB and
PostgreSQL have here and Redis does not. Proving it in the artifact's own smoke test is what makes
that a fact about the package rather than a discovery made later.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import socket
import struct
import subprocess
import time
from pathlib import Path


def free_port() -> int:
    """A port nothing is listening on, as the kernel's own answer rather than as a guess.

    Racy in principle — it is closed before mongod binds it — and the alternative is a hard-coded
    27017, which is *reliably* wrong on a machine already running a MongoDB, including a
    developer's.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def document(body: bytes) -> bytes:
    """Wrap BSON element bytes as a document: its own length, the elements, a terminator."""
    return struct.pack("<i", len(body) + 5) + body + b"\x00"


def hello_message() -> bytes:
    """``{hello: 1, $db: "admin"}`` as one OP_MSG, header included.

    Written out rather than assembled by a driver because there is no driver here and there is not
    going to be one: the whole of what this needs is one command that every server answers.
    """
    elements = (
        b"\x10" + b"hello\x00" + struct.pack("<i", 1)          # int32 "hello": 1
        + b"\x02" + b"$db\x00" + struct.pack("<i", 6) + b"admin\x00"   # string "$db": "admin"
    )
    section = b"\x00" + document(elements)                     # section kind 0, one document
    body = struct.pack("<i", 0) + section                      # flagBits, then the section
    header = struct.pack("<iiii", 16 + len(body), 1, 0, 2013)  # length, requestID, responseTo, OP_MSG
    return header + body


def hello(port: int, seconds: float = 90) -> int:
    """Send ``{hello: 1}`` until the server answers, and answer with the reply's size.

    Retried rather than sent once, because a process that has been started is not yet a server that
    has opened its socket — which is the difference a health check exists to express, and the reason
    MixEngine's recipe will need one too.
    """
    message = hello_message()
    deadline = time.monotonic() + seconds
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as link:
                link.sendall(message)
                reply = link.recv(8192)
            if len(reply) > 16:
                return len(reply)
            last = OSError(f"answered {len(reply)} bytes, which is not a message")
        except OSError as refusal:
            last = refusal
        time.sleep(0.5)
    raise SystemExit(f"mongod never answered a hello on 127.0.0.1:{port}: {last}")


def server(tree: Path, version: str, provides: dict[str, str], windows: bool) -> list[str]:
    """Run the four things MixEngine will do, and answer with the commands that were run."""
    mongod = tree / provides["mongod"]
    data = tree.parent / "smoke-dbpath"
    data.mkdir(parents=True, exist_ok=True)
    log = tree.parent / "smoke-mongod.log"
    port = free_port()

    command = [
        str(mongod),
        "--dbpath", str(data),
        "--port", str(port),
        "--bind_ip", "127.0.0.1",
        "--logpath", str(log),
    ]
    if not windows:
        # Nothing here connects over one, and a socket left in /tmp outlives the test.
        command.append("--nounixsocket")

    ran = [" ".join(command)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        answered = hello(port)
        ran.append(f"hello on 127.0.0.1:{port} answered {answered} bytes")

        if windows:
            # There is no `mongod --shutdown` on Windows — upstream's build refuses the option — so
            # the administrative path and the signal path are not the same sentence on the two
            # systems, and saying which was used is the point of recording what ran.
            process.terminate()
            ran.append("terminate() — mongod --shutdown is not offered on Windows")
        else:
            shutdown = [str(mongod), "--dbpath", str(data), "--shutdown"]
            subprocess.run(shutdown, check=True, capture_output=True, timeout=120)
            ran.append(" ".join(shutdown))

        process.wait(timeout=120)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=60)

    if log.exists():
        tail = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.strip()]
        if tail:
            print(f"mongod's last word: {tail[-1][:200]}")

    print(f"smoke: MongoDB {version} started, answered and stopped on port {port}")
    return ran
