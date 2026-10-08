import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import mkindex  # noqa: E402

INDEX = {
    "schema": 1,
    "generated_at": "2026-09-30T04:29:22Z",
    "packages": [{
        "kind": "caddy", "version": "2.11.4", "channel": "stable",
        "artifacts": [{"os": "linux", "arch": "x86_64", "url": "https://example.invalid/c.tar.zst",
                       "sha256": "00", "size": 1, "provides": {"caddy": "caddy"}}],
    }],
}


class Serialise(unittest.TestCase):
    def test_the_document_is_the_same_document(self):
        self.assertEqual(json.loads(mkindex.serialise(INDEX)), INDEX)

    def test_it_is_one_line_with_no_indentation(self):
        raw = mkindex.serialise(INDEX)
        self.assertEqual(raw.count(b"\n"), 1)
        self.assertTrue(raw.endswith(b"}\n"))
        self.assertNotIn(b'", "', raw)

    def test_keys_stay_in_the_order_a_reader_of_schema_1_expects(self):
        self.assertTrue(mkindex.serialise(INDEX).startswith(b'{"schema":1,"generated_at":'))


class Found(unittest.TestCase):
    def test_what_gather_found_is_merged_like_anything_collected(self):
        artifact = INDEX["packages"][0]["artifacts"][0]
        path = Path(tempfile.mkdtemp()) / "found.json"
        path.write_text(json.dumps([["caddy", "2.11.5", artifact]]))

        merged = mkindex.merge(json.loads(json.dumps(INDEX)), mkindex.read_found(path), {}, "stable")

        self.assertEqual([p["version"] for p in merged["packages"]], ["2.11.4", "2.11.5"])

    def test_no_file_is_nothing_found(self):
        self.assertEqual(mkindex.read_found(None), [])


class Write(unittest.TestCase):
    def test_both_encodings_are_written_side_by_side(self):
        base = "https://github.com/mixnz/mixengine-packages/releases/download"
        index = json.loads(json.dumps(INDEX))
        index["packages"][0]["artifacts"][0]["url"] = (
            f"{base}/caddy-2.11.4/caddy-2.11.4-linux-x86_64.tar.zst")
        out = Path(tempfile.mkdtemp()) / "dist" / "index.json"

        written = mkindex.write(index, out, base)

        self.assertEqual(sorted(path.name for path in written),
                         ["index-v2-caddy.json", "index-v2.json", "index.json"])
        self.assertEqual(json.loads(out.read_bytes()), index)
        root = json.loads((out.parent / "index-v2.json").read_bytes())
        self.assertEqual(root["generated_at"], index["generated_at"])
        self.assertEqual(list(root["kinds"]), ["caddy"])


class Lacks(unittest.TestCase):
    """T206: an artifact's `lacks` reaches the index, where MixEngine can read it."""

    def collected(self, manifest: dict) -> dict:
        directory = Path(tempfile.mkdtemp())
        archive = directory / "ruby-3.4.11-windows-x86_64.zip"
        archive.write_bytes(b"zip")
        (directory / f"{archive.name}.json").write_text(json.dumps(manifest))
        found = mkindex.collect(directory, "https://example.invalid/releases/download")
        return found[0][2]

    def manifest(self, **extra) -> dict:
        return {"kind": "ruby", "version": "3.4.11", "os": "windows", "arch": "x86_64",
                "provides": {"ruby": "bin/ruby.exe"}, "smoke": {"relocated": True}, **extra}

    def test_lacks_reaches_the_index(self):
        lacks = {"native gems": "no compiler", "yjit": "not built"}
        self.assertEqual(self.collected(self.manifest(lacks=lacks))["lacks"], lacks)

    def test_an_artifact_lacking_nothing_writes_no_field(self):
        self.assertNotIn("lacks", self.collected(self.manifest()))


if __name__ == "__main__":
    unittest.main()
