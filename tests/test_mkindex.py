import json
import sys
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


if __name__ == "__main__":
    unittest.main()
