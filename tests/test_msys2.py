import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import msys2  # noqa: E402


class Cells(unittest.TestCase):
    def test_each_cell_names_its_toolchain_and_compiler(self):
        self.assertEqual(msys2.CELLS[("windows", "x86_64")]["toolchain"],
                         ["base-devel", "mingw-w64-ucrt-x86_64-toolchain"])
        self.assertEqual(msys2.CELLS[("windows", "x86_64")]["compiler"], "ucrt64/bin/gcc.exe")
        self.assertEqual(msys2.CELLS[("windows", "aarch64")]["toolchain"],
                         ["base-devel", "mingw-w64-clang-aarch64-toolchain"])
        self.assertEqual(msys2.CELLS[("windows", "aarch64")]["compiler"],
                         "clangarm64/bin/clang.exe")

    def test_the_version_is_the_build_date(self):
        self.assertEqual(msys2.version_of("2026-10-08"), "2026.10.08")

    def test_provides_names_bash_and_the_compiler(self):
        self.assertEqual(msys2.provides(("windows", "x86_64")),
                         {"bash": "usr/bin/bash.exe", "gcc": "ucrt64/bin/gcc.exe"})
        self.assertEqual(msys2.provides(("windows", "aarch64")),
                         {"bash": "usr/bin/bash.exe", "clang": "clangarm64/bin/clang.exe"})


if __name__ == "__main__":
    unittest.main()
