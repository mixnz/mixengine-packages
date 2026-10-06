import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import node  # noqa: E402

NODE_24 = [("libc.so.6", Path("/lib/libc.so.6")), ("libstdc++.so.6", Path("/lib/libstdc++.so.6")),
           ("libgcc_s.so.1", Path("/lib/libgcc_s.so.1"))]
NODE_26 = NODE_24 + [("libatomic.so.1", Path("/lib/x86_64-linux-gnu/libatomic.so.1"))]


class BundleForeign(unittest.TestCase):
    def setUp(self):
        # `bundle_foreign` runs on the Linux cells only, and `relocate.is_system` judges by the
        # platform it is running on, so the test runs as the Linux runner would.
        linux = mock.patch.object(node.relocate.sys, "platform", "linux")
        linux.start()
        self.addCleanup(linux.stop)
        self.tree = Path(tempfile.mkdtemp())
        (self.tree / "bin").mkdir()
        (self.tree / "bin" / "node").write_bytes(b"")

    def test_a_node_that_needs_only_the_system_is_not_touched(self):
        with mock.patch.object(node.relocate, "dependencies", return_value=NODE_24), \
                mock.patch.object(node.relocate, "bundle") as bundle:
            changed = {"bin/node": "stripped"}
            self.assertEqual(node.bundle_foreign(self.tree, changed), [])
        bundle.assert_not_called()
        self.assertEqual(changed, {"bin/node": "stripped"})

    def test_libatomic_is_bundled_licensed_and_declared(self):
        origin = Path("/lib/x86_64-linux-gnu/libatomic.so.1")
        with mock.patch.object(node.relocate, "dependencies", return_value=NODE_26), \
                mock.patch.object(node.relocate, "bundle",
                                  return_value={"libatomic.so.1": origin}) as bundle, \
                mock.patch.object(node.relocate, "bundled_licences") as licences:
            changed = {"bin/node": "stripped"}
            with contextlib.redirect_stdout(io.StringIO()) as said:
                added = node.bundle_foreign(self.tree, changed)
        self.assertIn("bundled libatomic.so.1", said.getvalue())
        bundle.assert_called_once()
        licences.assert_called_once_with(self.tree, {"libatomic.so.1": origin})
        self.assertEqual(added, ["lib/libatomic.so.1"])
        self.assertIn("stripped", changed["bin/node"])
        self.assertIn("$ORIGIN/../lib", changed["bin/node"])


if __name__ == "__main__":
    unittest.main()
