import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import msys2  # noqa: E402
import parity  # noqa: E402


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

    def test_provides_names_the_compiler_cc_on_both_cells(self):
        # One command set per version: gather.py refuses cells whose commands disagree.
        self.assertEqual(msys2.provides(("windows", "x86_64")),
                         {"bash": "usr/bin/bash.exe", "cc": "ucrt64/bin/gcc.exe"})
        self.assertEqual(msys2.provides(("windows", "aarch64")),
                         {"bash": "usr/bin/bash.exe", "cc": "clangarm64/bin/clang.exe"})


class Keeps(unittest.TestCase):
    def tree(self, paths):
        root = Path(tempfile.mkdtemp(prefix="msys2-keeps-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for path in paths:
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(b"")
        return root

    def test_keeps_every_directory_holding_a_linker_input(self):
        root = self.tree([
            "ucrt64/lib/libm.a",
            "ucrt64/lib/gcc/x86_64-w64-mingw32/16.2.0/libgcc.a",
            "ucrt64/include/stdio.h",
            "usr/lib/libfoo.a",
            "usr/bin/bash.exe",
        ])
        kept = msys2.keeps(root)
        # Headers under `ucrt64/include` are not the rule's: its `include` is anchored at the root.
        self.assertEqual(sorted(kept), ["ucrt64/lib", "usr/lib"])
        for reason in kept.values():
            self.assertIn("compiler", reason)

    def test_every_surplus_path_is_covered(self):
        root = self.tree(["clangarm64/lib/clang/22/lib/windows/libclang_rt.builtins-aarch64.a",
                          "clangarm64/lib/libucrt.a", "clangarm64/bin/clang.exe"])
        kept = msys2.keeps(root)
        for path in ("clangarm64/lib/clang/22/lib/windows/libclang_rt.builtins-aarch64.a",
                     "clangarm64/lib/libucrt.a"):
            self.assertIsNotNone(parity.declared(path, kept))
        self.assertIsNone(parity.declared("clangarm64/bin/clang.exe", kept))


if __name__ == "__main__":
    unittest.main()
