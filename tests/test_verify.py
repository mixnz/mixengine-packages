import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import catalogue  # noqa: E402
import verify  # noqa: E402

BASE = "https://github.com/mixnz/mixengine-packages/releases/download"


def package(kind, version):
    return {"kind": kind, "version": version, "channel": "stable", "artifacts": [{
        "os": "linux", "arch": "x86_64",
        "url": f"{BASE}/{kind}-{version}/{kind}-{version}-linux-x86_64.tar.zst",
        "sha256": "0" * 64, "size": 7, "provides": {kind: f"bin/{kind}"}}]}


def index(*packages):
    return {"schema": 1, "generated_at": "2026-09-30T04:29:22Z", "packages": list(packages)}


INDEX = index(package("caddy", "2.11.4"), package("node", "22.1.0"))


class Catalogue(unittest.TestCase):
    def test_a_set_that_says_what_the_index_says_has_no_problems(self):
        self.assertEqual(verify.catalogue_problems(INDEX, catalogue.encode(INDEX, BASE), None), [])

    def test_a_set_encoded_from_a_different_index_is_refused_by_name(self):
        other = index(package("caddy", "2.11.4"), package("node", "22.2.0"))
        problems = verify.catalogue_problems(INDEX, catalogue.encode(other, BASE), None)
        self.assertEqual(problems, [
            "node 22.1.0 is in index.json and reads differently, or not at all, in schema 2",
            "node 22.2.0 is in schema 2 and not in index.json"])

    def test_a_root_stamped_at_another_moment_is_refused(self):
        later = dict(INDEX, generated_at="2026-10-01T00:00:00Z")
        problems = verify.catalogue_problems(INDEX, catalogue.encode(later, BASE), None)
        self.assertEqual(len(problems), 1)
        self.assertIn("generated_at", problems[0])

    def test_a_broken_set_is_reported_as_broken_and_not_decoded(self):
        files = catalogue.encode(INDEX, BASE)
        del files["index-v2-node.json"]
        self.assertEqual(verify.catalogue_problems(INDEX, files, None),
                         ["the root names node and there is no index-v2-node.json"])

    def test_a_kind_the_published_root_names_may_not_disappear(self):
        published = {"kinds": {"caddy": {}, "node": {}, "redis": {}}}
        problems = verify.catalogue_problems(INDEX, catalogue.encode(INDEX, BASE), published)
        self.assertEqual(problems, ["redis was in the published root and is not in this one"])


class Published(unittest.TestCase):
    def test_no_source_and_no_file_are_both_nothing_published(self):
        self.assertIsNone(verify.load_published(None))
        self.assertIsNone(verify.load_published(str(Path(tempfile.mkdtemp()) / "absent.json")))

    def test_a_file_that_is_there_is_read(self):
        path = Path(tempfile.mkdtemp()) / "index.json"
        path.write_text(json.dumps(INDEX))
        self.assertEqual(verify.load_published(str(path)), INDEX)


class Lost(unittest.TestCase):
    def test_a_version_the_published_index_had_is_still_a_failure(self):
        problems = verify.invariants(index(package("caddy", "2.11.4")), INDEX)
        self.assertEqual(problems,
                         ["node 22.1.0 was in the published index and is not in this one"])


if __name__ == "__main__":
    unittest.main()
