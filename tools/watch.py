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
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eol  # noqa: E402  — siblings, and this directory is not importable as a package
import upstream  # noqa: E402

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


def failures_by_title(runs: list[dict], since: str = "") -> dict[str, int]:
    """Failed release runs per title, created on or after *since* if given. A person's
    `(no release)` look at a version never counts."""
    counted: dict[str, int] = {}
    for run in runs:
        if run.get("createdAt", "")[:10] < since:
            continue
        if run.get("conclusion") == "failure" and not run["displayTitle"].endswith(NO_RELEASE):
            counted[run["displayTitle"]] = counted.get(run["displayTitle"], 0) + 1
    return counted


@dataclass
class Plan:
    build: list[tuple[str, str]] = field(default_factory=list)
    publish_only: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str, int]] = field(default_factory=list)
    new_lines: list[tuple[str, str]] = field(default_factory=list)
    # The newest version of each new line, built without a release so a person deciding whether to
    # add the line knows whether the recipes already handle it. Never published, never publishing.
    trials: list[tuple[str, str]] = field(default_factory=list)
    # Trials a previous run already dispatched, as (outcome, run id): each version is tried once.
    tried: dict[tuple[str, str], tuple[str, int]] = field(default_factory=dict)
    # Versions set aside in data/watch-ignore.json, as (kind, version, until). Shown by a dry run,
    # never reported: the point of the file is that the issue can close.
    ignored: list[tuple[str, str, str]] = field(default_factory=list)


# The day the watch began. What a line had before it is the floor nothing below is back-filled from;
# everything upstream published after it is owed, even once a newer patch has landed — otherwise a
# patch whose build failed on the day its successor succeeded would be passed over for good.
WATCH_SINCE = "2026-09-29"

# Versions a person has looked at and set aside for a while, each with the reason and the day it
# expires. See read_ignore.
IGNORE = Path(__file__).resolve().parent.parent / "data" / "watch-ignore.json"


def read_ignore(path: Path = IGNORE) -> dict[tuple[str, str], dict[str, str]]:
    """``{(kind, version): {"reason", "until"}}`` out of *path*; an entry that does not say both why
    and until when is refused, because an exception nobody can explain is one nobody can lift.

    Set aside *until* a date rather than for good. MySQL 8.0.45 was published with unsigned Linux
    tarballs; Oracle may add the signatures later, and a permanent entry would never notice. Once
    *until* passes, the version is built again and only failures from that day on are counted."""
    if not path.exists():
        return {}
    found: dict[tuple[str, str], dict[str, str]] = {}
    for key, entry in json.loads(path.read_text(encoding="utf-8")).items():
        if key.startswith("_"):
            continue
        pieces = key.split(" ")
        until = entry.get("until", "") if isinstance(entry, dict) else ""
        try:
            datetime.date.fromisoformat(until)
        except ValueError:
            until = ""
        if len(pieces) != 2 or not isinstance(entry, dict) or not entry.get("reason") or not until:
            raise SystemExit(f"{path}: {key!r} needs to be \"<kind> <version>\" with a reason and "
                             "an until date (YYYY-MM-DD)")
        found[(pieces[0], pieces[1])] = {"reason": entry["reason"], "until": until}
    return found


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
              failures: dict[tuple[str, str], int], threshold: int = 3,
              ignored: dict | None = None, today: str | None = None) -> Plan:
    """Decide what to build. Pure: everything it knows is passed in. *tags* maps each release tag
    to when it was created; *ignored* is `read_ignore`'s answer, honoured while *today* is before
    each entry's until."""
    ignored = ignored or {}
    today = today or datetime.date.today().isoformat()
    plan = Plan()
    for kind in sorted(index):
        if kind in EXCLUDED or kind not in upstream:
            continue
        floor = floors(kind, index[kind], tags)
        top = max(floor, key=parts)

        new_lines: dict[str, str] = {}
        for version in sorted(set(upstream[kind]), key=parts):
            line = line_of(kind, version)
            if line not in floor:
                if parts(line) > parts(top) and not NOT_OFFERED.get(kind, lambda _: False)(line):
                    new_lines[line] = version  # ascending, so the last one written is the newest
                continue
            if parts(version) <= parts(floor[line]) or version in index[kind]:
                continue
            if f"{kind}-{version}" in tags:
                plan.publish_only.append((kind, version))
                continue
            aside = ignored.get((kind, version))
            if aside and today < aside["until"]:
                plan.ignored.append((kind, version, aside["until"]))
                continue
            failed = failures.get((kind, version), 0)
            if failed >= threshold:
                plan.skipped.append((kind, version, failed))
                continue
            plan.build.append((kind, version))
        for line in sorted(new_lines, key=parts):
            plan.new_lines.append((kind, line))
            plan.trials.append((kind, new_lines[line]))
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
                        "--json", "databaseId,displayTitle,status,conclusion,createdAt")
        return json.loads(out)

    def dispatch(self, workflow: str, fields: dict[str, str]) -> None:
        flags = [item for key, value in fields.items() for item in ("-f", f"{key}={value}")]
        self._run("workflow", "run", workflow, *flags)

    def failed_jobs(self, run_id: int) -> list[str]:
        out = self._run("run", "view", str(run_id), "--json", "jobs")
        return [job["name"] for job in json.loads(out)["jobs"] if job["conclusion"] == "failure"]

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


def gather(gh, index: dict[str, list[str]], ask=upstream.versions, ignored: dict | None = None,
           today: str | None = None) -> tuple[Plan, dict[str, str]]:
    """Ask upstream and GitHub what `make_plan` needs. A kind that cannot be asked is reported."""
    ignored = ignored or {}
    answers: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    failures: dict[tuple[str, str], int] = {}
    runs_of: dict[str, list[dict]] = {}
    for kind, versions in index.items():
        if kind in EXCLUDED or kind not in WORKFLOWS:
            continue
        try:
            answers[kind] = ask(kind, {line_of(kind, version) for version in versions})
        except (SystemExit, OSError, ValueError, KeyError) as error:
            errors[kind] = str(error)
            continue
        runs = gh.runs(WORKFLOWS[kind][0])
        runs_of[kind] = runs
        for version in answers[kind]:
            # A version back from being set aside starts its count again on the day it came back.
            since = ignored.get((kind, version), {}).get("until", "")
            counted = failures_by_title(runs, since)
            if title(kind, version) in counted:
                failures[(kind, version)] = counted[title(kind, version)]
    plan = make_plan(index, answers, gh.tags(), failures, ignored=ignored, today=today)
    for kind, version in plan.trials:
        wanted = title(kind, version) + NO_RELEASE
        for run in runs_of.get(kind, []):  # newest first
            if run["displayTitle"] == wanted:
                outcome = run["conclusion"] if run["status"] == "completed" else "running"
                plan.tried[(kind, version)] = (outcome or "failure", run["databaseId"])
                break
    return plan, errors


LIMIT = 4
APPEAR_WITHIN = 120  # seconds GitHub may take to list a dispatched run


def _start(gh, kind: str, version: str, clock, sleep, release: bool = True) -> int | None:
    """Dispatch one exact version and return its run id, found by title among ids not seen before."""
    workflow, field_name = WORKFLOWS[kind]
    wanted = title(kind, version) + ("" if release else NO_RELEASE)
    before = {run["databaseId"] for run in gh.runs(workflow)}
    try:
        gh.dispatch(workflow, {field_name: version, "release": "true" if release else "false"})
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
              poll: float = 60, clock=time.monotonic, sleep=time.sleep,
              trials: list[tuple[str, str]] = ()):
    """Build every job, at most *limit* at once, until done or *deadline* (on *clock*).

    *trials* share the limit and are dispatched after the jobs, without a release."""
    results: dict[tuple[str, str], tuple[str, int | None]] = {}
    waiting = list(jobs) + list(trials)
    tried = set(trials)
    flying: dict[tuple[str, str], int] = {}
    while waiting or flying:
        while waiting and len(flying) < limit and clock() < deadline:
            job = waiting.pop(0)
            run_id = _start(gh, *job, clock=clock, sleep=sleep, release=job not in tried)
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
    built = any(results.get(job, ("",))[0] == "success" for job in plan.build)
    return built or bool(plan.publish_only)


def _link(run_id: int | None) -> str:
    return f"https://github.com/{REPO}/actions/runs/{run_id}" if run_id else "—"


def adding(kind: str, line: str, version: str) -> list[str]:
    """The steps that add a new line whose trial passed, as release/README.md's "A new line" says.

    The exact version and not the line, for the reason in this file's docstring. The end-of-life
    steps only for the kinds tools/eol.py transcribes; the others carry no date at all."""
    steps = [f"`release/build.sh {kind} {version}`", "`release/publish.sh`"]
    if kind in eol.SOURCES:
        steps += [f"`python tools/eol.py --update --kind {kind}`, then commit `data/eol.json`",
                  "`release/publish.sh` again, so the index carries the date"]
    steps.append(f"Add a **{line}** row to the {kind} table in README.md — ✅ for each artifact the "
                 "release carries, — for the rest, with the reason in docs/packages/")
    return [f"To add {kind} {line}:", ""] + [f"{n}. {step}" for n, step in enumerate(steps, 1)]


def render(plan: Plan, errors: dict[str, str], results: dict, published: str | None,
           trials: dict | None = None, failed_legs: dict | None = None) -> str | None:
    """The issue body, or None when there is nothing a person needs to know.

    *trials* is each new line's trial as (outcome, run id), *failed_legs* the jobs of a failed one."""
    trials, failed_legs = trials or {}, failed_legs or {}
    built = {job: result for job, result in results.items() if job not in plan.trials}
    trouble = [job for job, (outcome, _) in built.items() if outcome != "success"]
    if not (trouble or plan.skipped or plan.new_lines or errors):
        return None
    out = ["Written by `tools/watch.py` on its daily run; edited in place, closed when empty.", ""]
    if built:
        out += ["## Built today", "", "| Version | Outcome | Run |", "| --- | --- | --- |"]
        out += [f"| {kind} {version} | {outcome} | {_link(run_id)} |"
                for (kind, version), (outcome, run_id) in built.items()]
        out += ["", f"Index publish: **{published or 'not run'}**", ""]
        if trouble:
            out += ["Nothing to do for a version that did not succeed today: it is built again "
                    "tomorrow, and moves to \"Needs a person\" after three failed release runs.", ""]
    if plan.skipped:
        out += ["## Needs a person — no longer retried", ""]
        out += [f"- {kind} {version}: {count} failed release runs — once the recipe is fixed, "
                f"`release/build.sh {kind} {version}` then `release/publish.sh`"
                for kind, version, count in plan.skipped]
        kind, version, _ = plan.skipped[0]
        out += ["", "If upstream is at fault and may fix it later, set the version aside in "
                "`data/watch-ignore.json` instead:", "", "```json",
                f'"{kind} {version}": {{"reason": "<why>", "until": "<YYYY-MM-DD>"}}', "```", ""]
    if plan.new_lines:
        out += ["## New lines upstream — follow \"A new line\" in release/README.md", "",
                "Each is built once at its newest version without a release, to show whether the "
                "recipes already handle it. Adding the line is still a person's decision.", ""]
        trial_of = {(kind, line_of(kind, version)): (kind, version) for kind, version in plan.trials}
        steps: list[str] = []
        for kind, line in plan.new_lines:
            trial = trial_of.get((kind, line))
            if trial is None:
                out.append(f"- {kind} {line}")
                continue
            outcome, run_id = trials.get(trial, ("not tried", None))
            said = f"- {kind} {line} — trial of {trial[1]}: **{outcome}**"
            if failed_legs.get(trial):
                said += f" in {', '.join(failed_legs[trial])}"
            out.append(said + (f" ({_link(run_id)})" if run_id else ""))
            if outcome == "success":
                steps += [""] + adding(kind, line, trial[1])
            elif outcome == "failure":
                steps += ["", f"To try {kind} {line} again once the recipe is fixed: "
                              f"`release/build.sh {kind} {trial[1]} --no-release`, and add the "
                              "line only after it passes."]
        out += steps + [""]
    if errors:
        out += ["## Could not ask upstream", ""]
        out += [f"- {kind}: {error} — `python tools/upstream.py {kind}` asks the same by hand"
                for kind, error in sorted(errors.items())]
        out += ["", "Usually a publisher that did not answer in time; it is asked again tomorrow.",
                ""]
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
    plan, errors = gather(gh, read_index(), ignored=read_ignore())
    shown = {**plan.__dict__, "tried": {" ".join(key): value for key, value in plan.tried.items()}}
    print(json.dumps({**shown, "errors": errors}, indent=2))
    if not args.execute:
        return 0

    fresh = [trial for trial in plan.trials if trial not in plan.tried]
    results = build_all(gh, plan.build, deadline=started + BUDGET, trials=fresh)
    trials = {**plan.tried, **{trial: results[trial] for trial in fresh if trial in results}}
    failed_legs = {trial: gh.failed_jobs(run_id) for trial, (outcome, run_id) in trials.items()
                   if outcome == "failure" and run_id}
    published = None
    if should_publish(plan, results):
        published = _publish(gh, time.monotonic, time.sleep)
    gh.issue(render(plan, errors, results, published, trials, failed_legs))
    failed = published not in (None, "success")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
