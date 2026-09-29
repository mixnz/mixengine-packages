#!/usr/bin/env python3
"""Every stable version upstream lists, per kind — asked of the same source the recipe resolves.

Each kind reuses its recipe's own catalogue function wherever one exists, so the watcher and the
builder cannot disagree about what upstream said. The parsers are separate from the fetching so
they can be tested on a document instead of the network.

    py -3 tools/upstream.py php        # print what upstream has, for a person checking by hand

Python 3 stdlib only.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import borrow  # noqa: E402  — siblings, and this directory is not importable as a package

EXACT = re.compile(r"\d+\.\d+\.\d+")
PHP_RELEASES = "https://www.php.net/releases/index.php?json&version={major}&max=1000"
PHP_MAJORS = (7, 8)
# One cell is enough to learn which versions Microsoft published; a cell that lags is the build's
# problem, and fails there rather than here.
JAVA_TARGET = ("linux", "x86_64")


def recipe(name: str):
    return importlib.import_module(name)


def from_php(docs: list[dict]) -> list[str]:
    return [version for doc in docs for version in doc if EXACT.fullmatch(version)]


def from_node(entries: list[dict]) -> list[str]:
    found = [entry["version"].lstrip("v") for entry in entries]
    return [version for version in found if EXACT.fullmatch(version)]


def from_go(entries: list[dict]) -> list[str]:
    stable = re.compile(r"go(\d+\.\d+\.\d+)")
    return [
        match.group(1)
        for entry in entries
        if entry.get("stable") and (match := stable.fullmatch(entry.get("version", "")))
    ]


def from_github(releases: list[dict]) -> list[str]:
    found = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "").lstrip("v")
        if EXACT.fullmatch(tag):
            found.append(tag)
    return found


def from_ruby_index(text: str) -> list[str]:
    found = set()
    for row in text.splitlines()[1:]:
        columns = row.split("\t")
        if len(columns) < 2 or not columns[1].endswith(".tar.gz"):
            continue
        match = re.fullmatch(r"ruby-(\d+\.\d+\.\d+)", columns[0])
        if match:
            found.add(match.group(1))
    return sorted(found)


def from_python_sums(names: list[str], tag: str) -> list[str]:
    pattern = re.compile(rf"cpython-(\d+\.\d+\.\d+)\+{tag}-")
    return sorted({match.group(1) for name in names if (match := pattern.match(name))})


def from_mongodb(records: list[dict]) -> list[str]:
    return [
        record["version"]
        for record in records
        if record.get("production_release") and EXACT.fullmatch(record.get("version", ""))
    ]


def _php(lines: set[str]) -> list[str]:
    return from_php([
        json.loads(borrow.fetch(PHP_RELEASES.format(major=major))) for major in PHP_MAJORS
    ])


def _node(lines: set[str]) -> list[str]:
    return from_node(json.loads(borrow.fetch(f"{recipe('node').DIST}/index.json")))


def _go(lines: set[str]) -> list[str]:
    return from_go(json.loads(borrow.fetch(recipe("go").CATALOGUE)))


def _java(lines: set[str]) -> list[str]:
    java = recipe("java")
    return [
        entry["version"] for line in lines for entry in java.catalogue(int(line), JAVA_TARGET)
    ]


def _python(lines: set[str]) -> list[str]:
    python = recipe("python")
    tag = python.release_tag()
    return from_python_sums(list(python.catalogue(tag)), tag)


def _ruby(lines: set[str]) -> list[str]:
    text = borrow.fetch(recipe("ruby_unix").INDEX, timeout=300).decode("utf-8", "replace")
    return from_ruby_index(text)


def _github(module: str):
    return lambda lines: from_github(recipe(module).releases())


def _memcached(lines: set[str]) -> list[str]:
    return [name for name in recipe("memcached").tags() if EXACT.fullmatch(name)]


def _nginx(lines: set[str]) -> list[str]:
    return list(recipe("nginx").catalogue()["tar.gz"].values())


def _httpd(lines: set[str]) -> list[str]:
    return [".".join(map(str, key)) for key in recipe("httpd").catalogue()]


def _hashes(module: str):
    return lambda lines: [entry[0] for entry in recipe(module).catalogue().values()]


def _mariadb(lines: set[str]) -> list[str]:
    mariadb = recipe("mariadb")
    found = []
    for line in lines:
        releases = mariadb.get(f"{mariadb.API}/{line}/")["releases"]
        found += [version for version in releases if EXACT.fullmatch(version)]
    return found


def _mysql(lines: set[str]) -> list[str]:
    return [version for version in recipe("mysql").versions() if EXACT.fullmatch(version)]


def _postgres(lines: set[str]) -> list[str]:
    postgres = recipe("postgres")
    return [postgres.newest(major) for major in postgres.series().values()]


def _mongodb(lines: set[str]) -> list[str]:
    return from_mongodb(recipe("mongodb").catalogue(True))


SOURCES = {
    "php": _php,
    "node": _node,
    "python": _python,
    "ruby": _ruby,
    "go": _go,
    "java": _java,
    "caddy": _github("caddy"),
    "composer": _github("composer"),
    "mongosh": _github("mongosh"),
    "memcached": _memcached,
    "nginx": _nginx,
    "httpd": _httpd,
    "redis": _hashes("redis"),
    "valkey": _hashes("valkey"),
    "mariadb": _mariadb,
    "mysql": _mysql,
    "postgres": _postgres,
    "mongodb": _mongodb,
}
KINDS = tuple(SOURCES)


def versions(kind: str, lines: set[str]) -> list[str]:
    return sorted(set(SOURCES[kind](lines)), key=borrow.parts)


if __name__ == "__main__":
    asked = sys.argv[1]
    print("\n".join(versions(asked, set(sys.argv[2:]))))
