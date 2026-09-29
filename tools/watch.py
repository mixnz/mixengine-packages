#!/usr/bin/env python3
"""Notice a new patch upstream, build it, publish the index — every day, without a person.

`release/README.md` used to say that nothing tells you a new version exists. This is the thing that
does. It builds only patches of lines already in the index and newer than the newest one there; a
whole new line needs a README row and an end-of-life date, so it is reported and left to a person.
The design is docs/superpowers/specs/2026-09-30-upstream-watch-design.md.

Every version is dispatched **exactly**, never as a line: the Windows legs resolve a line against a
publisher that lags php.net by days, and a line dispatched on release day would file yesterday's
Windows build under today's tag.

Python 3 stdlib only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import upstream  # noqa: E402  — siblings, and this directory is not importable as a package

# Packed on demand and never back-filled, by its own design.
EXCLUDED = frozenset({"meilisearch"})

# How many leading parts of a version name its line, where that is not two. Matches the version
# column of each kind's table in README.md.
LINE_DEPTH = {"node": 1, "java": 1, "postgres": 1}

# kind -> (workflow, the input its version goes in). The three list kinds are given a list of one,
# so one run always names exactly one version.
WORKFLOWS = {
    "php": ("build-php.yml", "branch"),
    "mariadb": ("build-mariadb.yml", "versions"),
    "mysql": ("build-mysql.yml", "versions"),
    "postgres": ("build-postgres.yml", "versions"),
    **{
        kind: (f"build-{kind}.yml", "version")
        for kind in ("node", "python", "ruby", "go", "java", "caddy", "composer", "mongosh",
                     "memcached", "nginx", "httpd", "redis", "valkey", "mongodb")
    },
}


def parts(version: str) -> tuple[int, ...]:
    return tuple(int(piece) for piece in version.split("."))


def line_of(kind: str, version: str) -> str:
    return ".".join(version.split(".")[: LINE_DEPTH.get(kind, 2)])


NO_RELEASE = " (no release)"


def title(kind: str, version: str) -> str:
    """The run name a release build of *version* gets — see `run-name` in each build workflow."""
    return f"build {kind} {version}"


def failures_by_title(runs: list[dict]) -> dict[str, int]:
    """Failed release runs per title. A person's `(no release)` look at a version never counts."""
    counted: dict[str, int] = {}
    for run in runs:
        if run.get("conclusion") == "failure" and not run["displayTitle"].endswith(NO_RELEASE):
            counted[run["displayTitle"]] = counted.get(run["displayTitle"], 0) + 1
    return counted


@dataclass
class Plan:
    build: list[tuple[str, str]] = field(default_factory=list)
    publish_only: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str, int]] = field(default_factory=list)
    new_lines: list[tuple[str, str]] = field(default_factory=list)


def make_plan(index: dict[str, list[str]], upstream: dict[str, list[str]], tags: set[str],
              failures: dict[tuple[str, str], int], threshold: int = 3) -> Plan:
    """Decide what to build. Pure: everything it knows is passed in."""
    plan = Plan()
    for kind in sorted(index):
        if kind in EXCLUDED or kind not in upstream:
            continue
        newest: dict[str, str] = {}
        for version in index[kind]:
            line = line_of(kind, version)
            if line not in newest or parts(version) > parts(newest[line]):
                newest[line] = version
        top = max(newest, key=parts)

        new_lines: set[str] = set()
        for version in sorted(set(upstream[kind]), key=parts):
            line = line_of(kind, version)
            if line not in newest:
                if parts(line) > parts(top):
                    new_lines.add(line)
                continue
            if parts(version) <= parts(newest[line]):
                continue
            if f"{kind}-{version}" in tags:
                plan.publish_only.append((kind, version))
                continue
            failed = failures.get((kind, version), 0)
            if failed >= threshold:
                plan.skipped.append((kind, version, failed))
                continue
            plan.build.append((kind, version))
        plan.new_lines += [(kind, line) for line in sorted(new_lines, key=parts)]
    return plan


REPO = os.environ.get("GH_REPO", "mixnz/mixengine-packages")
INDEX_URL = f"https://github.com/{REPO}/releases/download/index/index.json"
LABEL = "upstream-watch"


class Gh:
    """The few `gh` calls this needs, and nothing else. Tests replace it with a fake."""

    def __init__(self, repo: str = REPO):
        self.repo = repo

    def _run(self, *args: str) -> str:
        return subprocess.run(
            ["gh", *args, "--repo", self.repo], check=True, capture_output=True, text=True
        ).stdout

    def tags(self) -> set[str]:
        out = self._run("release", "list", "--limit", "1000", "--json", "tagName")
        return {entry["tagName"] for entry in json.loads(out)}

    def runs(self, workflow: str) -> list[dict]:
        out = self._run("run", "list", "--workflow", workflow, "--limit", "200",
                        "--json", "databaseId,displayTitle,status,conclusion")
        return json.loads(out)

    def dispatch(self, workflow: str, fields: dict[str, str]) -> None:
        flags = [item for key, value in fields.items() for item in ("-f", f"{key}={value}")]
        self._run("workflow", "run", workflow, *flags)

    def view(self, run_id: int) -> dict:
        return json.loads(self._run("run", "view", str(run_id), "--json", "status,conclusion"))

    def issue(self, body: str | None) -> None:
        """Edit the one open report in place, open it if there is none, close it when *body* is None."""
        self._run("label", "create", LABEL, "--force", "--color", "0e8a16",
                  "--description", "Daily report of tools/watch.py")
        found = json.loads(self._run("issue", "list", "--label", LABEL, "--state", "open",
                                     "--json", "number"))
        if body is None:
            for entry in found:
                self._run("issue", "close", str(entry["number"]))
            return
        if found:
            self._run("issue", "edit", str(found[0]["number"]), "--body", body)
        else:
            self._run("issue", "create", "--title", "Upstream watch", "--label", LABEL,
                      "--body", body)


def read_index(url: str = INDEX_URL) -> dict[str, list[str]]:
    with urllib.request.urlopen(url, timeout=60) as response:
        document = json.loads(response.read())
    found: dict[str, list[str]] = {}
    for package in document["packages"]:
        found.setdefault(package["kind"], []).append(package["version"])
    return found


def gather(gh, index: dict[str, list[str]], ask=upstream.versions) -> tuple[Plan, dict[str, str]]:
    """Ask upstream and GitHub what `make_plan` needs. A kind that cannot be asked is reported."""
    answers: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    failures: dict[tuple[str, str], int] = {}
    for kind, versions in index.items():
        if kind in EXCLUDED or kind not in WORKFLOWS:
            continue
        try:
            answers[kind] = ask(kind, {line_of(kind, version) for version in versions})
        except (SystemExit, OSError, ValueError, KeyError) as error:
            errors[kind] = str(error)
            continue
        counted = failures_by_title(gh.runs(WORKFLOWS[kind][0]))
        for version in answers[kind]:
            if title(kind, version) in counted:
                failures[(kind, version)] = counted[title(kind, version)]
    return make_plan(index, answers, gh.tags(), failures), errors


LIMIT = 4
APPEAR_WITHIN = 120  # seconds GitHub may take to list a dispatched run


def _start(gh, kind: str, version: str, clock, sleep) -> int | None:
    """Dispatch one exact version and return its run id, found by title among ids not seen before."""
    workflow, field_name = WORKFLOWS[kind]
    wanted = title(kind, version)
    before = {run["databaseId"] for run in gh.runs(workflow)}
    gh.dispatch(workflow, {field_name: version, "release": "true"})
    waited_from = clock()
    while clock() - waited_from < APPEAR_WITHIN:
        for run in gh.runs(workflow):
            if run["displayTitle"] == wanted and run["databaseId"] not in before:
                return run["databaseId"]
        sleep(5)
    return None


def build_all(gh, jobs: list[tuple[str, str]], deadline: float, limit: int = LIMIT,
              poll: float = 60, clock=time.monotonic, sleep=time.sleep):
    """Build every job, at most *limit* at once, until done or *deadline* (on *clock*)."""
    results: dict[tuple[str, str], tuple[str, int | None]] = {}
    waiting = list(jobs)
    flying: dict[tuple[str, str], int] = {}
    while waiting or flying:
        while waiting and len(flying) < limit and clock() < deadline:
            job = waiting.pop(0)
            run_id = _start(gh, *job, clock=clock, sleep=sleep)
            if run_id is None:
                results[job] = ("lost", None)
            else:
                flying[job] = run_id
        for job, run_id in list(flying.items()):
            state = gh.view(run_id)
            if state["status"] == "completed":
                results[job] = (state["conclusion"] or "failure", run_id)
                del flying[job]
        if clock() >= deadline:
            break
        if flying:
            sleep(poll)
    for job, run_id in flying.items():
        results[job] = ("running", run_id)
    for job in waiting:
        results[job] = ("not dispatched", None)
    return results
