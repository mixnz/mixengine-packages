import hashlib
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import catalogue  # noqa: E402

BASE = "https://github.com/mixnz/mixengine-packages/releases/download"


def artifact(kind, version, os, arch, fmt="tar.zst", **more):
    return {"os": os, "arch": arch,
            "url": f"{BASE}/{kind}-{version}/{kind}-{version}-{os}-{arch}.{fmt}",
            "sha256": hashlib.sha256(f"{kind}{version}{os}{arch}".encode()).hexdigest(),
            "size": 1000 + len(version), "provides": {kind: f"bin/{kind}"}, **more}


def php(version):
    unix = {"requires": {"glibc": "2.35"}, "extension_dir": "ext",
            "extensions": {"static": ["core", "date"], "shared": ["xdebug"]}}
    return {"kind": "php", "version": version, "channel": "stable", "eol": "2029-12-31",
            "artifacts": [
                artifact("php", version, "linux", "aarch64", **unix),
                artifact("php", version, "linux", "x86_64", **unix),
                artifact("php", version, "windows", "x86_64", "zip",
                         requires={"vcredist": "2022"}, extension_dir="ext",
                         extensions={"static": ["core"], "shared": ["curl"], "enabled": ["curl"]}),
            ]}


# In the order mkindex writes them: by kind, then by version.
PACKAGES = [
    {"kind": "caddy", "version": "2.11.4", "channel": "stable", "artifacts": [
        artifact("caddy", "2.11.4", "linux", "x86_64"),
        artifact("caddy", "2.11.4", "macos", "aarch64", requires={"macos": "11.0"})]},
    {"kind": "java", "version": "25.0.4.1", "channel": "stable", "artifacts": [
        artifact("java", "25.0.4.1", "windows", "aarch64", "zip")]},
    {"kind": "memcached", "version": "1.6.45", "channel": "stable", "artifacts": [
        artifact("memcached", "1.6.45", "linux", "x86_64", "tar.gz")]},
    php("8.5.11"),
    {"kind": "postgres", "version": "18.6", "channel": "rc", "artifacts": [
        artifact("postgres", "18.6", "linux", "x86_64",
                 requires={"tzdata": "the system timezone database — Debian builds it that way"})]},
]


def index(packages=PACKAGES):
    return {"schema": 1, "generated_at": "2026-09-30T04:29:22Z",
            "packages": json.loads(json.dumps(packages))}


class RoundTrip(unittest.TestCase):
    def test_decoding_what_was_encoded_gives_the_same_packages(self):
        self.assertEqual(catalogue.decode(catalogue.encode(index(), BASE)), PACKAGES)

    def test_every_kind_has_its_own_file_and_the_root_names_each(self):
        files = catalogue.encode(index(), BASE)
        self.assertEqual(sorted(files), [
            "index-v2-caddy.json", "index-v2-java.json", "index-v2-memcached.json",
            "index-v2-php.json", "index-v2-postgres.json", "index-v2.json"])
        root = json.loads(files["index-v2.json"])
        self.assertEqual(root["schema"], 2)
        self.assertEqual(root["generated_at"], "2026-09-30T04:29:22Z")
        self.assertEqual(root["base_url"], BASE)
        self.assertEqual(sorted(root["kinds"]), ["caddy", "java", "memcached", "php", "postgres"])
        self.assertEqual(catalogue.problems(files), [])

    def test_a_kind_file_carries_no_url_and_no_timestamp(self):
        raw = catalogue.encode(index(), BASE)["index-v2-php.json"]
        self.assertNotIn(b"https://", raw)
        self.assertNotIn(b"generated_at", raw)
        self.assertEqual(json.loads(raw)["packages"][0]["artifacts"][2]["format"], "zip")

    def test_prose_in_a_shape_survives(self):
        files = catalogue.encode(index(), BASE)
        self.assertTrue(files["index-v2-postgres.json"].isascii())
        self.assertIn("—", catalogue.decode(files)[4]["artifacts"][0]["requires"]["tzdata"])


class Shapes(unittest.TestCase):
    def test_cells_that_say_the_same_thing_share_a_shape(self):
        document = json.loads(catalogue.encode(index(), BASE)["index-v2-php.json"])
        self.assertEqual(len(document["shapes"]), 2)
        self.assertEqual([a["shape"] for a in document["packages"][0]["artifacts"]], [0, 0, 1])

    def test_key_order_does_not_make_a_second_shape(self):
        one = artifact("caddy", "2.11.4", "linux", "x86_64",
                       requires={"glibc": "2.28", "cpu": "avx"}, extension_dir="ext")
        other = artifact("caddy", "2.11.4", "linux", "aarch64")
        other["extension_dir"] = "ext"
        other["requires"] = {"cpu": "avx", "glibc": "2.28"}
        package = {"kind": "caddy", "version": "2.11.4", "channel": "stable",
                   "artifacts": [other, one]}
        document = json.loads(catalogue.encode(index([package]), BASE)["index-v2-caddy.json"])
        self.assertEqual(len(document["shapes"]), 1)

    def test_a_shape_that_is_not_in_the_table_is_refused(self):
        files = catalogue.encode(index(), BASE)
        document = json.loads(files["index-v2-java.json"])
        for wrong in (1, -1, "0"):
            document["packages"][0]["artifacts"][0]["shape"] = wrong
            with self.assertRaises(SystemExit) as refused:
                catalogue.decode_kind(document, BASE)
            self.assertIn("names shape", str(refused.exception))


class Determinism(unittest.TestCase):
    def test_the_same_packages_give_the_same_bytes(self):
        self.assertEqual(catalogue.encode(index(), BASE), catalogue.encode(index(), BASE))

    def test_a_new_version_changes_its_own_kind_and_the_root_and_nothing_else(self):
        before = catalogue.encode(index(), BASE)
        after = catalogue.encode(index(PACKAGES[:4] + [php("8.5.12")] + PACKAGES[4:]), BASE)
        self.assertEqual(sorted(name for name in after if after[name] != before[name]),
                         ["index-v2-php.json", "index-v2.json"])
        self.assertEqual(catalogue.changed(after, json.loads(before["index-v2.json"])),
                         ["index-v2-php.json"])

    def test_with_nothing_published_every_kind_file_is_new(self):
        files = catalogue.encode(index(), BASE)
        self.assertEqual(len(catalogue.changed(files, None)), 5)
        self.assertEqual(catalogue.changed(files, json.loads(files["index-v2.json"])), [])


class Refusals(unittest.TestCase):
    def test_a_url_that_does_not_fit_the_pattern_is_not_encoded(self):
        for url in ("https://windows.php.net/downloads/php-8.5.11-Win32.zip",
                    f"{BASE}/php-8.5.11/php-8.5.11-linux-x86_64.tar.xz",
                    f"{BASE}/php-8.5.10/php-8.5.11-linux-x86_64.tar.zst"):
            packages = [php("8.5.11")]
            packages[0]["artifacts"][1]["url"] = url
            with self.assertRaises(SystemExit) as refused:
                catalogue.encode(index(packages), BASE)
            self.assertIn(url, str(refused.exception))

    def test_a_root_is_held_to_the_bytes_it_names(self):
        files = catalogue.encode(index(), BASE)

        longer = dict(files, **{"index-v2-php.json": files["index-v2-php.json"] + b"\n"})
        self.assertEqual(len(catalogue.problems(longer)), 2)  # its size and its hash

        swapped = dict(files, **{"index-v2-java.json": files["index-v2-java.json"].replace(
            b"25.0.4.1", b"25.0.4.2")})
        self.assertEqual(catalogue.problems(swapped),
                         ["index-v2-java.json does not hash to what the root says"])

        missing = {name: raw for name, raw in files.items() if name != "index-v2-caddy.json"}
        self.assertEqual(catalogue.problems(missing),
                         ["the root names caddy and there is no index-v2-caddy.json"])

        extra = dict(files, **{"index-v2-ghost.json": b"{}\n"})
        self.assertEqual(catalogue.problems(extra),
                         ["index-v2-ghost.json is not named by the root"])

        self.assertEqual(catalogue.problems({}), ["there is no index-v2.json"])


class Fetch(unittest.TestCase):
    def error(self, code):
        return urllib.error.HTTPError("https://example.invalid/x", code, "", {}, io.BytesIO())

    def test_nothing_published_yet_is_none(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.error(404)):
            self.assertIsNone(catalogue.fetch("https://example.invalid/x"))

    def test_a_server_that_failed_is_not_read_as_nothing_published(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.error(503)):
            with self.assertRaises(urllib.error.HTTPError):
                catalogue.fetch("https://example.invalid/x")


if __name__ == "__main__":
    unittest.main()
