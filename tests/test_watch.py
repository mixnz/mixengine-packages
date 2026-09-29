import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import watch  # noqa: E402


class LineOf(unittest.TestCase):
    def test_major_minor_by_default(self):
        self.assertEqual(watch.line_of("php", "8.4.26"), "8.4")

    def test_major_for_node_java_postgres(self):
        self.assertEqual(watch.line_of("node", "22.23.2"), "22")
        self.assertEqual(watch.line_of("java", "21.0.12.1"), "21")
        self.assertEqual(watch.line_of("postgres", "18.6"), "18")


class MakePlan(unittest.TestCase):
    def test_builds_every_patch_newer_than_the_index(self):
        plan = watch.make_plan(
            index={"php": ["8.4.24"]},
            upstream={"php": ["8.4.23", "8.4.24", "8.4.25", "8.4.26"]},
            tags=set(), failures={},
        )
        self.assertEqual(plan.build, [("php", "8.4.25"), ("php", "8.4.26")])

    def test_never_back_fills_older_than_the_newest_in_the_index(self):
        plan = watch.make_plan(
            index={"php": ["8.4.24"]}, upstream={"php": ["8.4.20", "8.4.24"]},
            tags=set(), failures={},
        )
        self.assertEqual(plan.build, [])

    def test_compares_numerically(self):
        plan = watch.make_plan(
            index={"go": ["1.27.9"]}, upstream={"go": ["1.27.9", "1.27.10"]},
            tags=set(), failures={},
        )
        self.assertEqual(plan.build, [("go", "1.27.10")])

    def test_existing_tag_is_published_not_rebuilt(self):
        plan = watch.make_plan(
            index={"php": ["8.4.24"]}, upstream={"php": ["8.4.25"]},
            tags={"php-8.4.25"}, failures={},
        )
        self.assertEqual(plan.build, [])
        self.assertEqual(plan.publish_only, [("php", "8.4.25")])

    def test_skips_after_threshold_failures(self):
        plan = watch.make_plan(
            index={"mysql": ["8.0.44"]}, upstream={"mysql": ["8.0.45"]},
            tags=set(), failures={("mysql", "8.0.45"): 3},
        )
        self.assertEqual(plan.build, [])
        self.assertEqual(plan.skipped, [("mysql", "8.0.45", 3)])

    def test_new_line_is_reported_not_built(self):
        plan = watch.make_plan(
            index={"php": ["8.5.9"]}, upstream={"php": ["8.5.9", "8.6.0"]},
            tags=set(), failures={},
        )
        self.assertEqual(plan.build, [])
        self.assertEqual(plan.new_lines, [("php", "8.6")])

    def test_old_line_not_in_index_is_neither_built_nor_new(self):
        plan = watch.make_plan(
            index={"php": ["8.5.9"]}, upstream={"php": ["5.6.40", "8.5.9"]},
            tags=set(), failures={},
        )
        self.assertEqual((plan.build, plan.new_lines), ([], []))

    def test_meilisearch_is_never_watched(self):
        plan = watch.make_plan(
            index={"meilisearch": ["1.53.2"]}, upstream={"meilisearch": ["1.53.3"]},
            tags=set(), failures={},
        )
        self.assertEqual(plan.build, [])

    def test_kind_without_upstream_answer_is_left_alone(self):
        plan = watch.make_plan(index={"php": ["8.4.24"]}, upstream={}, tags=set(), failures={})
        self.assertEqual(plan.build, [])

    def test_planned_versions_are_exact_upstream_versions(self):
        upstream = {"php": ["8.4.25"], "node": ["22.24.0"]}
        plan = watch.make_plan(
            index={"php": ["8.4.24"], "node": ["22.23.2"]}, upstream=upstream,
            tags=set(), failures={},
        )
        for kind, version in plan.build:
            self.assertIn(version, upstream[kind])


class Titles(unittest.TestCase):
    def test_title_matches_the_workflow_run_name(self):
        self.assertEqual(watch.title("php", "8.4.26"), "build php 8.4.26")

    def test_every_watched_kind_has_a_workflow(self):
        import upstream
        for kind in upstream.KINDS:
            self.assertIn(kind, watch.WORKFLOWS)

    def test_failures_count_release_runs_only(self):
        runs = [
            {"displayTitle": "build mysql 8.0.45", "conclusion": "failure"},
            {"displayTitle": "build mysql 8.0.45", "conclusion": "failure"},
            {"displayTitle": "build mysql 8.0.45 (no release)", "conclusion": "failure"},
            {"displayTitle": "build mysql 8.0.45", "conclusion": "cancelled"},
            {"displayTitle": "build mysql 8.4.10", "conclusion": "success"},
        ]
        self.assertEqual(watch.failures_by_title(runs), {"build mysql 8.0.45": 2})

    def test_every_build_workflow_has_the_run_name(self):
        root = Path(__file__).resolve().parent.parent / ".github" / "workflows"
        for kind, (workflow, field_name) in watch.WORKFLOWS.items():
            text = (root / workflow).read_text(encoding="utf-8")
            expected = (
                f"run-name: build {kind} ${{{{ inputs.{field_name} }}}}"
                "${{ !inputs.release && ' (no release)' || '' }}"
            )
            self.assertIn(expected, text, workflow)


if __name__ == "__main__":
    unittest.main()
