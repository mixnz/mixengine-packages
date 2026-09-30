import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import no_clobber  # noqa: E402


def incoming(*cells):
    """A download-artifact directory holding one manifest (and its archive) per cell."""
    directory = Path(tempfile.mkdtemp())
    for kind, version, cell in cells:
        archive = directory / f"{kind}-{version}-{cell}.tar.zst"
        archive.write_bytes(b"")
        Path(f"{archive}.json").write_text(json.dumps({"kind": kind, "version": version}))
    return directory


class Planned(unittest.TestCase):
    def test_every_cell_is_filed_under_the_version_its_manifest_states(self):
        directory = incoming(("php", "8.2.34", "linux-x86_64"), ("php", "8.2.33", "linux-aarch64"))
        self.assertEqual(no_clobber.planned(directory), {
            "php-8.2.33": ["php-8.2.33-linux-aarch64.tar.zst", "php-8.2.33-linux-aarch64.tar.zst.json"],
            "php-8.2.34": ["php-8.2.34-linux-x86_64.tar.zst", "php-8.2.34-linux-x86_64.tar.zst.json"],
        })


class Conflicts(unittest.TestCase):
    def test_a_leg_that_built_an_older_published_version_is_caught(self):
        planned = {
            "php-8.2.33": ["php-8.2.33-linux-aarch64.tar.zst", "php-8.2.33-linux-aarch64.tar.zst.json"],
            "php-8.2.34": ["php-8.2.34-linux-x86_64.tar.zst", "php-8.2.34-linux-x86_64.tar.zst.json"],
        }
        existing = {"php-8.2.33": {"php-8.2.33-linux-aarch64.tar.zst",
                                   "php-8.2.33-linux-aarch64.tar.zst.json"}}
        self.assertEqual(
            no_clobber.conflicts(planned, lambda tag: existing.get(tag, set())),
            {"php-8.2.33": ["php-8.2.33-linux-aarch64.tar.zst",
                            "php-8.2.33-linux-aarch64.tar.zst.json"]},
        )

    def test_adding_a_missing_cell_to_an_existing_release_is_fine(self):
        planned = {"php-8.2.34": ["php-8.2.34-macos-x86_64.tar.zst",
                                  "php-8.2.34-macos-x86_64.tar.zst.json"]}
        existing = {"php-8.2.34": {"php-8.2.34-linux-x86_64.tar.zst"}}
        self.assertEqual(no_clobber.conflicts(planned, lambda tag: existing.get(tag, set())), {})


class Main(unittest.TestCase):
    def test_refuses_without_replace_and_allows_with_it(self):
        directory = incoming(("ruby", "3.4.10", "windows-x86_64"))
        taken = lambda tag: {"ruby-3.4.10-windows-x86_64.tar.zst"}  # noqa: E731
        self.assertEqual(no_clobber.main([str(directory)], existing=taken), 1)
        self.assertEqual(no_clobber.main([str(directory), "--replace"], existing=taken), 0)

    def test_nothing_taken_passes(self):
        directory = incoming(("ruby", "3.4.11", "windows-x86_64"))
        self.assertEqual(no_clobber.main([str(directory)], existing=lambda tag: set()), 0)


class Workflows(unittest.TestCase):
    def test_every_build_workflow_checks_before_it_uploads_and_never_clobbers_by_default(self):
        root = Path(__file__).resolve().parent.parent / ".github" / "workflows"
        for workflow in sorted(root.glob("build-*.yml")):
            text = workflow.read_text(encoding="utf-8")
            check = text.index("python3 tools/no_clobber.py incoming")
            upload = text.index('gh release upload "$tag"')
            self.assertLess(check, upload, workflow.name)
            self.assertIn('gh release upload "$tag" "${assets[@]}" ${REPLACE:+--clobber}', text,
                          workflow.name)
            self.assertNotIn('"${assets[@]}" --clobber', text, workflow.name)


if __name__ == "__main__":
    unittest.main()
