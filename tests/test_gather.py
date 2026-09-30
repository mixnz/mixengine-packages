import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import gather  # noqa: E402

BASE = "https://github.com/mixnz/mixengine-packages/releases/download"


def release(tag, *archives, manifests=True):
    """A release as the API lists it: ``(name, hex digest or None, size)`` per archive."""
    assets = []
    for name, digest, size in archives:
        assets.append({"name": name, "size": size,
                       "digest": f"sha256:{digest}" if digest else None})
        if manifests:
            assets.append({"name": f"{name}.json", "size": 1500, "digest": "sha256:" + "f" * 64})
    return {"tag_name": tag, "assets": assets}


def index(*cells):
    """A published index holding ``(kind, version, archive name, hex digest, size)`` cells."""
    packages = {}
    for kind, version, name, digest, size in cells:
        package = packages.setdefault((kind, version), {
            "kind": kind, "version": version, "channel": "stable", "artifacts": []})
        package["artifacts"].append({
            "os": "linux", "arch": "x86_64", "url": f"{BASE}/{kind}-{version}/{name}",
            "sha256": digest, "size": size, "provides": {kind: f"bin/{kind}"}})
    return {"schema": 1, "generated_at": "2026-09-30T04:29:22Z",
            "packages": list(packages.values())}


A, B = "a" * 64, "b" * 64
PHP = "php-8.5.11-linux-x86_64.tar.zst"
PHP_ARM = "php-8.5.11-linux-aarch64.tar.zst"


class Verdicts(unittest.TestCase):
    def test_a_version_the_index_describes_exactly_is_not_looked_at(self):
        look, said = gather.verdicts([release("php-8.5.11", (PHP, A, 10))],
                                     index(("php", "8.5.11", PHP, A, 10)))
        self.assertEqual((look, said), ([], []))

    def test_a_version_not_in_the_index_is_looked_at(self):
        look, _ = gather.verdicts(
            [release("php-8.5.11", (PHP, A, 10)), release("php-8.5.12", (PHP, A, 10))],
            index(("php", "8.5.11", PHP, A, 10)))
        self.assertEqual(look, ["php-8.5.12"])

    def test_a_cell_added_to_a_published_version_is_looked_at(self):
        look, said = gather.verdicts([release("php-8.5.11", (PHP, A, 10), (PHP_ARM, B, 11))],
                                     index(("php", "8.5.11", PHP, A, 10)))
        self.assertEqual(look, ["php-8.5.11"])
        self.assertIn("a cell the index does not have", said[0])

    def test_replaced_bytes_are_looked_at_and_said_out_loud(self):
        for listed in ((PHP, B, 10), (PHP, A, 11)):
            look, said = gather.verdicts([release("php-8.5.11", listed)],
                                         index(("php", "8.5.11", PHP, A, 10)))
            self.assertEqual(look, ["php-8.5.11"])
            self.assertIn("published bytes were replaced", said[0])

    def test_an_asset_with_no_digest_is_looked_at(self):
        look, said = gather.verdicts([release("php-8.5.11", (PHP, None, 10))],
                                     index(("php", "8.5.11", PHP, A, 10)))
        self.assertEqual(look, ["php-8.5.11"])
        self.assertIn("no digest", said[0])

    def test_a_cell_gone_from_the_release_is_a_warning_and_not_a_reason_to_look(self):
        look, said = gather.verdicts(
            [release("php-8.5.11", (PHP, A, 10))],
            index(("php", "8.5.11", PHP, A, 10), ("php", "8.5.11", PHP_ARM, B, 11)))
        self.assertEqual(look, [])
        self.assertTrue(said[0].startswith("::warning::php-8.5.11"))
        self.assertIn(PHP_ARM, said[0])

    def test_a_version_with_no_release_at_all_is_a_warning(self):
        look, said = gather.verdicts(
            [release("php-8.5.11", (PHP, A, 10))],
            index(("php", "8.5.11", PHP, A, 10), ("node", "22.1.0", "node.tar.zst", B, 5)))
        self.assertEqual(look, [])
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].startswith("::warning::node-22.1.0 "))

    def test_an_archive_with_no_manifest_beside_it_is_not_an_artifact(self):
        source = release("mysql-5.7.44", ("mysql-5.7.44-patched-src.tar.gz", A, 10),
                         manifests=False)
        self.assertEqual(gather.cells(source), {})
        self.assertEqual(gather.verdicts([source, release("php-8.5.11", (PHP, A, 10))],
                                         index(("php", "8.5.11", PHP, A, 10))), ([], []))

    def test_with_no_published_index_every_version_is_looked_at(self):
        look, _ = gather.verdicts(
            [release("php-8.5.11", (PHP, A, 10)), release("node-22.1.0", ("n.tar.zst", B, 5))],
            {"schema": 1, "packages": []})
        self.assertEqual(look, ["node-22.1.0", "php-8.5.11"])


class Recheck(unittest.TestCase):
    RELEASES = [release("mongodb-8.0.32", ("mongodb.zip", A, 1)),
                release("mongosh-2.11.1", ("mongosh.zip", A, 1)),
                release("java-25.0.4.1", ("java.zip", A, 1))]
    INDEX = index(("mongodb", "8.0.32", "mongodb.zip", A, 1),
                  ("mongosh", "2.11.1", "mongosh.zip", A, 1),
                  ("java", "25.0.4.1", "java.zip", A, 1))

    def test_a_kind_is_rechecked_and_no_other(self):
        look, said = gather.verdicts(self.RELEASES, self.INDEX, "mongodb")
        self.assertEqual(look, ["mongodb-8.0.32"])
        self.assertIn("recheck was asked for", said[0])

    def test_all_rechecks_every_version(self):
        look, _ = gather.verdicts(self.RELEASES, self.INDEX, "all")
        self.assertEqual(look, ["java-25.0.4.1", "mongodb-8.0.32", "mongosh-2.11.1"])

    def test_a_kind_that_is_a_prefix_of_another_claims_nothing(self):
        self.assertFalse(gather.of_kind("mongodb-8.0.32", "mongo"))
        self.assertTrue(gather.of_kind("java-25.0.4.1", "java"))
        with self.assertRaises(SystemExit) as refused:
            gather.verdicts(self.RELEASES, self.INDEX, "mongo")
        self.assertIn("mongo", str(refused.exception))


class Listing(unittest.TestCase):
    def test_an_empty_listing_against_a_full_index_is_refused(self):
        with self.assertRaises(SystemExit) as refused:
            gather.verdicts([], index(("php", "8.5.11", PHP, A, 10)))
        self.assertIn("listing", str(refused.exception))


def fake_download(tag, directory):
    """What `gh release download` leaves: one archive and its manifest."""
    archive = directory / f"{tag}-linux-x86_64.tar.zst"
    archive.write_bytes(b"bytes of " + tag.encode())
    kind, version = tag.rsplit("-", 1)
    Path(f"{archive}.json").write_text(json.dumps({
        "kind": kind, "version": version, "os": "linux", "arch": "x86_64",
        "provides": {kind: f"bin/{kind}"}, "smoke": {"relocated": True}}))


class Gather(unittest.TestCase):
    def test_each_version_is_read_and_gone_before_the_next(self):
        work = Path(tempfile.mkdtemp())
        seen = []

        def download(tag, directory):
            seen.append(sorted(path.name for path in work.iterdir()))
            fake_download(tag, directory)

        found, refused = gather.gather(["node-22.1.0", "php-8.5.11"], BASE, work,
                                       download=download, parity=lambda directory: True)

        self.assertEqual(seen, [["node-22.1.0"], ["php-8.5.11"]])
        self.assertEqual(list(work.iterdir()), [])
        self.assertEqual(refused, [])
        self.assertEqual([(kind, version) for kind, version, _ in found],
                         [("node", "22.1.0"), ("php", "8.5.11")])
        self.assertEqual(found[1][2]["url"],
                         f"{BASE}/php-8.5.11/php-8.5.11-linux-x86_64.tar.zst")
        self.assertEqual(found[1][2]["size"], len(b"bytes of php-8.5.11"))

    def test_a_version_whose_cells_disagree_is_named_and_the_rest_still_looked_at(self):
        work = Path(tempfile.mkdtemp())
        found, refused = gather.gather(
            ["node-22.1.0", "php-8.5.11"], BASE, work, download=fake_download,
            parity=lambda directory: directory.name != "node-22.1.0")

        self.assertEqual(refused, ["node-22.1.0"])
        self.assertEqual([kind for kind, _, _ in found], ["php"])
        self.assertEqual(list(work.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
