#!/usr/bin/env python3
"""Borrow a Meilisearch Community Edition binary and repack it as a MixEngine artifact.

**The Community Edition, and only it.** Every release publishes two binaries per target, and the
repository is `MIT AND BUSL-1.1`. What separates them was read out of upstream's
`publish-release-assets.yml` rather than inferred: the matrix builds `edition: [community,
enterprise]` and only the enterprise leg passes `--features enterprise`. So `meilisearch-<target>` is
compiled without the Business Source code, and `meilisearch-enterprise-<target>` is never taken.

**One file, and a service.** The payload is a single executable, as Caddy's is, so the whole proof
is running it: indexing a document and finding it again, from a directory it has been moved to.

**The digest is GitHub's, because Meilisearch publishes none.** There is no checksums file among the
assets. The release API reports a `sha256:` digest for every asset, computed by GitHub at upload, and
that is what the download is checked against — weaker than a document the publisher wrote, and
recorded in `upstream.verified_against` as exactly what it is.

**Which cells a release has is read off that release**, the way `caddy.py` does it. `v1.53.2` has no
`meilisearch-macos-amd64` although every earlier release has one and its enterprise twin does, so a
floor written down here would be wrong in one direction or the other.

Python 3 stdlib only, by policy: this runs on a GitHub runner with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow  # noqa: E402  — siblings, and this directory is not importable as a package
import eol  # noqa: E402
import relocate  # noqa: E402
import strip  # noqa: E402

API = "https://api.github.com/repos/meilisearch/meilisearch/releases"
RAW = "https://raw.githubusercontent.com/meilisearch/meilisearch"

# (os, arch) -> the Community Edition asset upstream publishes for it. No Windows ARM64: upstream's
# release matrix builds `windows-2022` only, and has never built anything else for Windows.
TARGETS = {
    ("windows", "x86_64"): "meilisearch-windows-amd64.exe",
    ("macos", "aarch64"): "meilisearch-macos-apple-silicon",
    ("macos", "x86_64"): "meilisearch-macos-amd64",
    ("linux", "x86_64"): "meilisearch-linux-amd64",
    ("linux", "aarch64"): "meilisearch-linux-aarch64",
}

MAJOR = 1

LICENCE = "LICENSE-MIT"


def releases() -> list[dict]:
    """Every Meilisearch release on the first two pages, newest first.

    The GitHub API, with a token when the runner has one: unauthenticated requests are limited to
    sixty an hour per address, and runners share addresses.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    found: list[dict] = []
    for page in (1, 2):
        try:
            page_of = json.loads(borrow.fetch(f"{API}?per_page=100&page={page}", headers=headers))
        except urllib.error.HTTPError as error:
            raise SystemExit(f"the Meilisearch release listing answered {error.code}") from error
        found += page_of
        if len(page_of) < 100:
            break
    return found


def resolve(spec: str, target: tuple[str, str]) -> tuple[str, str, str]:
    """Turn ``1``, ``1.53``, ``1.53.2`` or ``latest`` into ``(version, asset url, sha256)``.

    A release that exists and has no asset for this cell is an empty cell (exit 75); a version that
    does not exist is a refusal.
    """
    asset = TARGETS[target]
    asked = () if spec == "latest" else borrow.parts(spec)
    if asked and asked[0] != MAJOR:
        raise SystemExit(f"MixEngine offers Meilisearch {MAJOR}.x; {spec!r} is not one")

    matching: list[tuple[tuple[int, ...], dict]] = []
    for release in releases():
        if release.get("draft") or release.get("prerelease"):
            continue
        match = re.fullmatch(r"v(\d+\.\d+\.\d+)", release.get("tag_name", ""))
        if not match or borrow.parts(match.group(1))[0] != MAJOR:
            continue
        key = borrow.parts(match.group(1))
        if key[: len(asked)] == asked:
            matching.append((key, release))

    if not matching:
        raise SystemExit(f"meilisearch/meilisearch has no stable release matching {spec!r}")

    # The newest release that matches, and only it: falling back to an older patch because the
    # newest one lacks this cell would publish a version whose other cells do not exist.
    version_key, release = max(matching, key=lambda pair: pair[0])
    version = ".".join(map(str, version_key))
    assets = {entry["name"]: entry for entry in release.get("assets", ())}
    if asset not in assets:
        borrow.unavailable(f"Meilisearch v{version} publishes no {asset}")

    digest = assets[asset].get("digest") or ""
    if not digest.startswith("sha256:") or len(digest) != len("sha256:") + 64:
        raise SystemExit(f"v{version}'s {asset} carries no SHA-256 digest in the release API: {digest!r}")
    return version, assets[asset]["browser_download_url"], digest.removeprefix("sha256:")


def binary_name(operating_system: str) -> str:
    """What the executable is called inside the artifact: upstream's asset, less its target suffix.

    A bare file has no layout to preserve, so this is the least renaming that makes `provides` say
    the same thing on every cell — the precedent is Composer's `composer.phar`.
    """
    return "meilisearch.exe" if operating_system == "windows" else "meilisearch"


def licence(tree: Path, version: str) -> str:
    """Write the MIT licence of this release into *tree*, and answer with its name.

    From the release's own tag rather than from `main`, so the text is the one that release shipped
    under. `LICENSE-EE` is not fetched: its absence is the point of taking the Community binary.
    """
    try:
        text = borrow.fetch(f"{RAW}/v{version}/{LICENCE}")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"v{version} has no {LICENCE} at its tag ({error.code})") from error
    if b"MIT License" not in text and b"Permission is hereby granted" not in text:
        raise SystemExit(f"{LICENCE} at v{version} does not read as the MIT licence")
    (tree / LICENCE).write_bytes(text)
    return LICENCE


def vcredist(binary: Path) -> str | None:
    """`2022` when the Windows executable imports the Visual C++ runtime, which 1.53.2's does.

    Upstream ships nothing beside the executable, so an imported runtime is always the machine's
    precondition — there is no bundled copy to discount, unlike the JDK.
    """
    imported = [name.lower() for name in relocate.pe_imports(binary)]
    runtime = sorted(name for name in imported if name.startswith(("vcruntime140", "msvcp140")))
    print(f"imports {', '.join(runtime) or 'no VC++ runtime'}")
    return "2022" if runtime else None


def describe(
    tree: Path, version: str, target: tuple[str, str], url: str, digest: str,
    added: list[str], changed: dict[str, str],
) -> dict:
    """What is in the artifact, as the daemon will read it."""
    operating_system, arch = target
    name = binary_name(operating_system)
    if not (tree / name).is_file():
        raise SystemExit(f"the artifact provides no {name}")
    manifest = {
        "schema": 1,
        "kind": "meilisearch",
        "version": version,
        "os": operating_system,
        "arch": arch,
        "source": "borrowed",
        "upstream": {
            "url": url,
            "sha256": digest,
            "verified_against": "the sha256 digest GitHub's release API states for the asset; "
                                "Meilisearch publishes no checksums of its own",
            "project": "meilisearch/meilisearch",
            "variant": "Community Edition, built without --features enterprise",
        },
        "provides": {"meilisearch": name},
    }
    return borrow.declare(tree, manifest, added=added, changed=changed)


def free_port() -> int:
    """A port nothing is listening on, as the kernel's own answer — racy, and better than 7700."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def call(url: str, body: object | None = None, timeout: float = 10) -> dict:
    """One JSON request to the server under test, answering with the decoded body."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="GET" if body is None else "POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def smoke(tree: Path, version: str, manifest: dict) -> dict:
    """Run the artifact from somewhere it has never been, and make it be a search engine there.

    `--version` proves a binary. What a daemon will do is start it, wait for it to be healthy, and
    then use it — so the test indexes one document, waits for the task that does it, and finds the
    document again, which is the only step that exercises what the 296 MB of embedded tokenizer data
    in 1.53.2 is for.

    `--env development` so no master key is needed, `--no-analytics` because a smoke test must not
    report home, and every path the server writes — the database, dumps, snapshots — under a
    temporary directory, so nothing lands in the runner's working directory.
    """
    elsewhere = borrow.moved(tree)
    problems = relocate.verify(elsewhere, directories=("",))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        raise SystemExit("the relocated tree reaches outside itself")

    binary = elsewhere / manifest["provides"]["meilisearch"]
    path = borrow.clean_path(binary.parent)
    banner = borrow.run(binary, "--version", path=path, drop=("MEILI",))
    if banner != f"meilisearch {version}":
        raise SystemExit(f"meilisearch reports {banner!r}, expected 'meilisearch {version}'")

    work = borrow.long_name(Path(tempfile.mkdtemp(prefix="mixengine-meili-")))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    log = work / "meilisearch.log"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("MEILI")}
    environment["PATH"] = path
    with log.open("wb") as sink:
        process = subprocess.Popen(
            [str(binary), "--db-path", str(work / "data.ms"), "--http-addr", f"127.0.0.1:{port}",
             "--env", "development", "--no-analytics",
             "--dump-dir", str(work / "dumps"), "--snapshot-dir", str(work / "snapshots")],
            stdout=sink, stderr=subprocess.STDOUT, env=environment, cwd=str(work),
        )

    def said() -> str:
        return log.read_text(encoding="utf-8", errors="replace")[-3000:]

    try:
        deadline = time.monotonic() + 120
        while True:
            if process.poll() is not None:
                raise SystemExit(f"meilisearch exited {process.returncode} before it was healthy\n{said()}")
            try:
                if call(f"{base}/health", timeout=2).get("status") == "available":
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise SystemExit(f"{base}/health never answered available\n{said()}")
            time.sleep(0.5)

        reported = call(f"{base}/version").get("pkgVersion")
        if reported != version:
            raise SystemExit(f"GET /version reports {reported!r}, expected {version}")

        queued = call(f"{base}/indexes/smoke/documents",
                      [{"id": 1, "title": f"mixengine meilisearch {version}"}])
        task = queued["taskUid"]
        deadline = time.monotonic() + 120
        while True:
            status = call(f"{base}/tasks/{task}").get("status")
            if status == "succeeded":
                break
            if status in ("failed", "canceled") or time.monotonic() > deadline:
                raise SystemExit(f"indexing task {task} ended {status!r}\n{said()}")
            time.sleep(0.5)

        hits = call(f"{base}/indexes/smoke/search", {"q": "mixengine"}).get("hits", [])
        if [hit.get("id") for hit in hits] != [1]:
            raise SystemExit(f"searching for the indexed document found {hits!r}")

        process.terminate()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            raise SystemExit("meilisearch did not exit after being asked to stop") from None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)

    borrow.discard(elsewhere)
    shutil.rmtree(work, ignore_errors=True)
    name = manifest["provides"]["meilisearch"]
    return {
        "relocated": True,
        "ran": [
            f"{name} --version",
            f"{name} --env development --no-analytics, GET /health and GET /version",
            "a document added, its indexing task succeeded, and a search found it",
            "the server stopped",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", required=True,
        help="an exact version (1.53.2), a minor (1.53) or major (1) for its newest release, or 'latest'",
    )
    parser.add_argument("--out", default="dist", type=Path)
    args = parser.parse_args()

    target = borrow.host("Meilisearch")
    operating_system = target[0]
    version, url, expected = resolve(args.version, target)
    if version != args.version:
        print(f"{args.version} resolved to {version}")
    eol.announce("meilisearch", version)

    work = Path(tempfile.mkdtemp(prefix="mixengine-meilisearch-"))
    tree = work / "tree"
    tree.mkdir()
    binary = tree / binary_name(operating_system)
    print(f"borrowing {url}")
    try:
        urllib.request.urlretrieve(url, binary)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{url} answered {error.code}") from error

    actual = borrow.sha256(binary)
    if actual != expected:
        raise SystemExit(f"sha256 mismatch: got {actual}, the release API states {expected}")
    print(f"sha256 {actual} (verified against the digest GitHub's release API states)")
    if operating_system != "windows":
        binary.chmod(0o755)

    added = [licence(tree, version)]
    # Expected to change nothing: neither 1.53.1 nor 1.53.2 carries debug information, and the size
    # of the newer one is embedded data. Called so that a release which differs is declared.
    changed = strip.debug(tree)

    manifest = describe(tree, version, target, url, actual, added, changed)
    manifest["smoke"] = smoke(tree, version, manifest)

    if operating_system == "windows":
        needed = vcredist(binary)
        if needed:
            manifest["requires"] = {"vcredist": needed}
            print(f"needs the Visual C++ {needed} redistributable")
    else:
        measured = relocate.floor(tree, directories=("",))
        if measured:
            manifest["requires"] = {measured[0]: measured[1]}
            print(f"needs {measured[0]} {measured[1]} or newer")

    borrow.publish(tree, manifest, args.out, "zip" if operating_system == "windows" else "tar.gz")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
