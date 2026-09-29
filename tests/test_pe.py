import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pe  # noqa: E402
from pe_builder import make_dll  # noqa: E402


class Reader(unittest.TestCase):
    def test_exports(self):
        self.assertEqual(pe.exports(make_dll(exports=["zend_a", "zend_b"])), {"zend_a", "zend_b"})

    def test_a_dll_without_exports(self):
        self.assertEqual(pe.exports(make_dll()), set())

    def test_imports_are_keyed_by_lowercase_dll(self):
        dll = make_dll(imports={"PHP8.dll": ["zend_a"], "KERNEL32.dll": ["Sleep"]})
        self.assertEqual(pe.imports(dll), {"php8.dll": ["zend_a"], "kernel32.dll": ["Sleep"]})


class Unresolved(unittest.TestCase):
    def test_names_what_the_tree_does_not_export(self):
        with tempfile.TemporaryDirectory() as tree:
            (Path(tree) / "php8.dll").write_bytes(make_dll(exports=["zend_a"]))
            extension = make_dll(imports={"php8.dll": ["zend_a", "php_win32_ioutil_path_kind_w"],
                                          "kernel32.dll": ["Sleep"]})
            self.assertEqual(pe.unresolved(extension, Path(tree)),
                             {"php8.dll": ["php_win32_ioutil_path_kind_w"]})

    def test_system_dlls_are_not_the_tree_s_business(self):
        with tempfile.TemporaryDirectory() as tree:
            (Path(tree) / "php8.dll").write_bytes(make_dll(exports=["zend_a"]))
            extension = make_dll(imports={"php8.dll": ["zend_a"], "kernel32.dll": ["Sleep"]})
            self.assertEqual(pe.unresolved(extension, Path(tree)), {})


if __name__ == "__main__":
    unittest.main()
