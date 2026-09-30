#!/usr/bin/env python3
"""Notice a new patch upstream, build it, publish the index — every day, without a person.

`release/README.md` used to say that nothing tells you a new version exists. This is the thing that
does. It builds only patches of lines already in the index, published since the watch began; a
whole new line needs a README row and an end-of-life date, so it is reported and left to a person.
The design is docs/superpowers/specs/2026-09-30-upstream-watch-design.md.

Every version is dispatched **exactly**, never as a line: the Windows legs resolve a line against a
publisher that lags php.net by days, and a line dispatched on release day would file yesterday's
Windows build under today's tag.

Python 3 stdlib only.
"""

from __future__ import annotations

import argparse
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

# Lines upstream publishes that this repository does not offer, so a new one is not news. Node's
# odd-numbered lines are Current releases that never become LTS and end after about eight months;
# the Node row has only ever carried the even ones.
NOT_OFFERED = {"node": lambda line: int(line) % 2 == 1}

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


# The day the watch began. What a line had before it is the floor nothing below is back-filled from;
# everything upstream published after it is owed, even once a newer patch has landed — otherwise a
# patch whose build failed on the day its successor succeeded would be passed over for good.
WATCH_SINCE = "2026-09-29"


def floors(kind: str, versions: list[str], tags: dict[str, str]) -> dict[str, str]:
    """Per line, the newest version published before the watch began, or — for a line first packed
    after it — the oldest version it has. A version whose tag is unknown counts as from before."""
    before: dict[str, list[str]] = {}
    after: dict[str, list[str]] = {}
    for version in versions:
        created = tags.get(f"{kind}-{version}", "")
        side = after if created and created[:10] >= WATCH_SINCE else before
        side.setdefault(line_of(kind, version), []).append(version)
    found = {line: min(found, key=parts) for line, found in after.items()}
    found.update({line: max(found, key=parts) for line, found in before.items()})
    return found


def make_plan(index: dict[str, list[str]], upstream: dict[str, list[str]], tags: dict[str, str],
              failures: dict[tuple[str, str], int], threshold: int = 3) -> Plan:
    """Decide what to build. Pure: everything it knows is passed in. *tags* maps each release tag
    to when it was created."""
    plan = Plan()
    for kind in sorted(index):
        if kind in EXCLUDED or kind not in upstream:
            continue
        floor = floors(kind, index[kind], tags)
        top = max(floor, key=parts)

        new_lines: set[str] = set()
        for version in sorted(set(upstream[kind]), key=parts):
            line = line_of(kind, version)
            if line not in floor:
                if parts(line) > parts(top) and not NOT_OFFERED.get(kind, lambda _: False)(line):
                    new_lines.add(line)
                continue
            if parts(version) <= parts(floor[line]) or version in index[kind]:
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

    def tags(self) -> dict[str, str]:
        out = self._run("release", "list", "--limit", "1000", "--json", "tagName,createdAt")
        return {entry["tagName"]: entry["createdAt"] for entry in json.loads(out)}

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
    try:
        gh.dispatch(workflow, {field_name: version, "release": "true"})
    except subprocess.CalledProcessError as error:
        # One refused dispatch must not end the run before the index is published and the report
        # written. It is reported as lost and tried again tomorrow.
        print(f"dispatching {wanted} failed: {error.stderr or error}", file=sys.stderr)
        return None
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


# The job is capped at six hours; stop dispatching and waiting early enough to publish and report.
BUDGET = 5 * 3600


def should_publish(plan: Plan, results: dict) -> bool:
    built = any(outcome == "success" for outcome, _ in results.values())
    return built or bool(plan.publish_only)


def _link(run_id: int | None) -> str:
    return f"https://github.com/{REPO}/actions/runs/{run_id}" if run_id else "—"


def render(plan: Plan, errors: dict[str, str], results: dict, published: str | None) -> str | None:
    """The issue body, or None when there is nothing a person needs to know."""
    trouble = [job for job, (outcome, _) in results.items() if outcome != "success"]
    if not (trouble or plan.skipped or plan.new_lines or errors):
        return None
    out = ["Written by `tools/watch.py` on its daily run; edited in place, closed when empty.", ""]
    if results:
        out += ["## Built today", "", "| Version | Outcome | Run |", "| --- | --- | --- |"]
        out += [f"| {kind} {version} | {outcome} | {_link(run_id)} |"
                for (kind, version), (outcome, run_id) in results.items()]
        out += ["", f"Index publish: **{published or 'not run'}**", ""]
    if plan.skipped:
        out += ["## Needs a person — no longer retried", ""]
        out += [f"- {kind} {version}: {count} failed release runs"
                for kind, version, count in plan.skipped]
        out += ["", "Fix the recipe, then `release/build.sh <kind> <version>` by hand.", ""]
    if plan.new_lines:
        out += ["## New lines upstream — follow \"A new line\" in release/README.md", ""]
        out += [f"- {kind} {line}" for kind, line in plan.new_lines]
        out += [""]
    if errors:
        out += ["## Could not ask upstream", ""]
        out += [f"- {kind}: {error}" for kind, error in sorted(errors.items())]
        out += [""]
    return "\n".join(out)


def _publish(gh, clock, sleep) -> str:
    before = {run["databaseId"] for run in gh.runs("publish-index.yml")}
    gh.dispatch("publish-index.yml", {"publish": "true"})
    for _ in range(24):
        sleep(5)
        fresh = [run for run in gh.runs("publish-index.yml") if run["databaseId"] not in before]
        if fresh:
            break
    else:
        return "lost"
    run_id = fresh[0]["databaseId"]
    while (state := gh.view(run_id))["status"] != "completed":
        sleep(30)
    return state["conclusion"] or "failure"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="dispatch builds, publish the index and write the issue; "
                             "without it the plan is printed and nothing is touched")
    args = parser.parse_args(argv)

    gh = Gh()
    started = time.monotonic()
    plan, errors = gather(gh, read_index())
    print(json.dumps({**plan.__dict__, "errors": errors}, indent=2))
    if not args.execute:
        return 0

    results = build_all(gh, plan.build, deadline=started + BUDGET)
    published = None
    if should_publish(plan, results):
        published = _publish(gh, time.monotonic, time.sleep)
    gh.issue(render(plan, errors, results, published))
    failed = published not in (None, "success")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
