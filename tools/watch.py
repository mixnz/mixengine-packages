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

from dataclasses import dataclass, field

# Packed on demand and never back-filled, by its own design.
EXCLUDED = frozenset({"meilisearch"})

# How many leading parts of a version name its line, where that is not two. Matches the version
# column of each kind's table in README.md.
LINE_DEPTH = {"node": 1, "java": 1, "postgres": 1}


def parts(version: str) -> tuple[int, ...]:
    return tuple(int(piece) for piece in version.split("."))


def line_of(kind: str, version: str) -> str:
    return ".".join(version.split(".")[: LINE_DEPTH.get(kind, 2)])


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
