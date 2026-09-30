import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import watch  # noqa: E402

BEFORE = "2026-08-17T10:00:00Z"
AFTER = "2026-09-29T19:00:00Z"


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
            tags={}, failures={},
        )
        self.assertEqual(plan.build, [("php", "8.4.25"), ("php", "8.4.26")])

    def test_never_back_fills_older_than_the_newest_in_the_index(self):
        plan = watch.make_plan(
            index={"php": ["8.4.24"]}, upstream={"php": ["8.4.20", "8.4.24"]},
            tags={}, failures={},
        )
        self.assertEqual(plan.build, [])

    def test_compares_numerically(self):
        plan = watch.make_plan(
            index={"go": ["1.27.9"]}, upstream={"go": ["1.27.9", "1.27.10"]},
            tags={}, failures={},
        )
        self.assertEqual(plan.build, [("go", "1.27.10")])

    def test_existing_tag_is_published_not_rebuilt(self):
        plan = watch.make_plan(
            index={"php": ["8.4.24"]}, upstream={"php": ["8.4.25"]},
            tags={"php-8.4.25": AFTER}, failures={},
        )
        self.assertEqual(plan.build, [])
        self.assertEqual(plan.publish_only, [("php", "8.4.25")])

    def test_skips_after_threshold_failures(self):
        plan = watch.make_plan(
            index={"mysql": ["8.0.44"]}, upstream={"mysql": ["8.0.45"]},
            tags={}, failures={("mysql", "8.0.45"): 3},
        )
        self.assertEqual(plan.build, [])
        self.assertEqual(plan.skipped, [("mysql", "8.0.45", 3)])

    def test_new_line_is_reported_not_built(self):
        plan = watch.make_plan(
            index={"php": ["8.5.9"]}, upstream={"php": ["8.5.9", "8.6.0"]},
            tags={}, failures={},
        )
        self.assertEqual(plan.build, [])
        self.assertEqual(plan.new_lines, [("php", "8.6")])

    def test_old_line_not_in_index_is_neither_built_nor_new(self):
        plan = watch.make_plan(
            index={"php": ["8.5.9"]}, upstream={"php": ["5.6.40", "8.5.9"]},
            tags={}, failures={},
        )
        self.assertEqual((plan.build, plan.new_lines), ([], []))

    def test_meilisearch_is_never_watched(self):
        plan = watch.make_plan(
            index={"meilisearch": ["1.53.2"]}, upstream={"meilisearch": ["1.53.3"]},
            tags={}, failures={},
        )
        self.assertEqual(plan.build, [])

    def test_kind_without_upstream_answer_is_left_alone(self):
        plan = watch.make_plan(index={"php": ["8.4.24"]}, upstream={}, tags={}, failures={})
        self.assertEqual(plan.build, [])

    def test_planned_versions_are_exact_upstream_versions(self):
        upstream = {"php": ["8.4.25"], "node": ["22.24.0"]}
        plan = watch.make_plan(
            index={"php": ["8.4.24"], "node": ["22.23.2"]}, upstream=upstream,
            tags={}, failures={},
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


class FakeGh:
    def __init__(self, tags=(), runs=None):
        self._tags, self._runs = dict(tags), runs or {}
        self.dispatched = []

    def tags(self):
        return self._tags

    def runs(self, workflow):
        return self._runs.get(workflow, [])


class Gather(unittest.TestCase):
    def test_an_unreachable_upstream_does_not_stop_the_others(self):
        def ask(kind, lines):
            if kind == "php":
                raise SystemExit("php.net answered 503")
            return {"node": ["22.24.0"]}[kind]

        plan, errors = watch.gather(
            FakeGh(), {"php": ["8.4.24"], "node": ["22.23.2"]}, ask=ask
        )
        self.assertEqual(plan.build, [("node", "22.24.0")])
        self.assertEqual(errors, {"php": "php.net answered 503"})

    def test_failures_come_from_release_runs_of_that_version(self):
        runs = {"build-mysql.yml": [
            {"displayTitle": "build mysql 8.0.45", "conclusion": "failure"}] * 3}
        plan, _ = watch.gather(
            FakeGh(runs=runs), {"mysql": ["8.0.44"]}, ask=lambda kind, lines: ["8.0.45"]
        )
        self.assertEqual(plan.skipped, [("mysql", "8.0.45", 3)])


class ScriptedGh:
    """A GitHub whose runs finish after a fixed number of polls."""

    def __init__(self, outcome=None, polls=1, appear=True):
        self.outcome = outcome or {}
        self.polls, self.appear = polls, appear
        self._runs, self._seen, self.dispatched = {}, {}, []
        self.in_flight_max, self._next = 0, 100

    def runs(self, workflow):
        return [dict(run) for run in self._runs.get(workflow, [])]

    def dispatch(self, workflow, fields):
        self.dispatched.append((workflow, dict(fields)))
        if not self.appear:
            return
        version = next(v for k, v in fields.items() if k != "release")
        kind = workflow[len("build-"):-len(".yml")]
        self._next += 1
        self._runs.setdefault(workflow, []).insert(0, {
            "databaseId": self._next, "displayTitle": watch.title(kind, version),
            "status": "in_progress", "conclusion": "",
        })
        self._seen[self._next] = (kind, version, 0)
        running = sum(1 for (_, _, n) in self._seen.values() if n >= 0)
        self.in_flight_max = max(self.in_flight_max, running)

    def view(self, run_id):
        kind, version, n = self._seen[run_id]
        if n + 1 >= self.polls:
            self._seen[run_id] = (kind, version, -1)
            return {"status": "completed",
                    "conclusion": self.outcome.get((kind, version), "success")}
        self._seen[run_id] = (kind, version, n + 1)
        return {"status": "in_progress", "conclusion": ""}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class BuildAll(unittest.TestCase):
    def test_dispatches_exact_versions_with_release_on(self):
        gh, clock = ScriptedGh(), Clock()
        watch.build_all(gh, [("php", "8.4.26")], deadline=10_000, clock=clock, sleep=clock.sleep)
        self.assertEqual(gh.dispatched, [("build-php.yml", {"branch": "8.4.26", "release": "true"})])

    def test_list_kinds_get_a_list_of_one(self):
        gh, clock = ScriptedGh(), Clock()
        watch.build_all(gh, [("mariadb", "11.8.9")], deadline=10_000, clock=clock, sleep=clock.sleep)
        self.assertEqual(gh.dispatched[0][1], {"versions": "11.8.9", "release": "true"})

    def test_never_more_than_the_limit_in_flight(self):
        gh, clock = ScriptedGh(polls=3), Clock()
        jobs = [("node", f"22.24.{n}") for n in range(9)]
        results = watch.build_all(gh, jobs, deadline=10_000, limit=4,
                                  clock=clock, sleep=clock.sleep)
        self.assertLessEqual(gh.in_flight_max, 4)
        self.assertEqual({outcome for outcome, _ in results.values()}, {"success"})

    def test_reports_each_outcome(self):
        gh, clock = ScriptedGh(outcome={("php", "8.4.25"): "failure"}), Clock()
        results = watch.build_all(gh, [("php", "8.4.25"), ("php", "8.4.26")],
                                  deadline=10_000, clock=clock, sleep=clock.sleep)
        self.assertEqual(results[("php", "8.4.25")][0], "failure")
        self.assertEqual(results[("php", "8.4.26")][0], "success")

    def test_deadline_leaves_runs_running_and_the_rest_undispatched(self):
        gh, clock = ScriptedGh(polls=1_000), Clock()
        jobs = [("node", f"22.24.{n}") for n in range(6)]
        results = watch.build_all(gh, jobs, deadline=300, limit=4, poll=60,
                                  clock=clock, sleep=clock.sleep)
        outcomes = [outcome for outcome, _ in results.values()]
        self.assertEqual(outcomes.count("running"), 4)
        self.assertEqual(outcomes.count("not dispatched"), 2)

    def test_a_run_that_never_appears_is_lost(self):
        gh, clock = ScriptedGh(appear=False), Clock()
        results = watch.build_all(gh, [("php", "8.4.26")], deadline=10_000,
                                  clock=clock, sleep=clock.sleep)
        self.assertEqual(results[("php", "8.4.26")], ("lost", None))

    def test_an_older_run_with_the_same_title_is_not_mistaken_for_the_new_one(self):
        gh, clock = ScriptedGh(), Clock()
        gh._runs["build-php.yml"] = [{"databaseId": 7, "displayTitle": "build php 8.4.26",
                                       "status": "completed", "conclusion": "failure"}]
        results = watch.build_all(gh, [("php", "8.4.26")], deadline=10_000,
                                  clock=clock, sleep=clock.sleep)
        self.assertEqual(results[("php", "8.4.26")][0], "success")
        self.assertNotEqual(results[("php", "8.4.26")][1], 7)


class Report(unittest.TestCase):
    def test_publish_when_anything_new_exists(self):
        empty = watch.Plan()
        self.assertFalse(watch.should_publish(empty, {}))
        self.assertTrue(watch.should_publish(empty, {("php", "8.4.26"): ("success", 1)}))
        self.assertFalse(watch.should_publish(empty, {("php", "8.4.26"): ("failure", 1)}))
        self.assertTrue(watch.should_publish(watch.Plan(publish_only=[("php", "8.4.25")]), {}))

    def test_nothing_to_say_closes_the_issue(self):
        self.assertIsNone(watch.render(watch.Plan(), {}, {}, None))

    def test_report_names_everything_a_person_must_act_on(self):
        plan = watch.Plan(
            build=[("php", "8.4.26"), ("mysql", "8.0.46")],
            skipped=[("mysql", "8.0.45", 3)],
            new_lines=[("php", "8.6")],
        )
        results = {("php", "8.4.26"): ("success", 11), ("mysql", "8.0.46"): ("failure", 12)}
        body = watch.render(plan, {"ruby": "timed out"}, results, "success")
        for expected in ("php 8.4.26", "success", "mysql 8.0.46", "actions/runs/12",
                         "mysql 8.0.45", "3 failed", "php 8.6", "ruby", "timed out"):
            self.assertIn(expected, body)


class RefusedDispatch(unittest.TestCase):
    def test_a_refused_dispatch_is_lost_not_fatal(self):
        import subprocess

        class Refusing(ScriptedGh):
            def dispatch(self, workflow, fields):
                raise subprocess.CalledProcessError(1, ["gh", "workflow", "run"])

        gh, clock = Refusing(), Clock()
        results = watch.build_all(gh, [("php", "8.4.26"), ("node", "24.21.0")],
                                  deadline=10_000, clock=clock, sleep=clock.sleep)
        self.assertEqual(results[("php", "8.4.26")], ("lost", None))
        self.assertEqual(results[("node", "24.21.0")], ("lost", None))


class Baseline(unittest.TestCase):
    def test_a_patch_that_failed_while_a_newer_one_landed_is_still_built(self):
        plan = watch.make_plan(
            index={"php": ["8.4.24", "8.4.26"]},
            upstream={"php": ["8.4.24", "8.4.25", "8.4.26"]},
            tags={"php-8.4.24": BEFORE, "php-8.4.26": AFTER}, failures={},
        )
        self.assertEqual(plan.build, [("php", "8.4.25")])

    def test_a_version_already_in_the_index_is_neither_built_nor_republished(self):
        plan = watch.make_plan(
            index={"php": ["8.4.24", "8.4.26"]},
            upstream={"php": ["8.4.24", "8.4.26"]},
            tags={"php-8.4.24": BEFORE, "php-8.4.26": AFTER}, failures={},
        )
        self.assertEqual((plan.build, plan.publish_only), ([], []))

    def test_gaps_from_before_the_watch_are_not_back_filled(self):
        plan = watch.make_plan(
            index={"php": ["8.4.20", "8.4.24"]},
            upstream={"php": ["8.4.20", "8.4.22", "8.4.24"]},
            tags={"php-8.4.20": BEFORE, "php-8.4.24": BEFORE}, failures={},
        )
        self.assertEqual(plan.build, [])

    def test_a_line_first_packed_after_the_watch_starts_at_its_oldest_version(self):
        plan = watch.make_plan(
            index={"php": ["8.5.9", "8.6.1"]},
            upstream={"php": ["8.6.0", "8.6.1", "8.6.2"]},
            tags={"php-8.5.9": BEFORE, "php-8.6.1": AFTER}, failures={},
        )
        self.assertEqual(plan.build, [("php", "8.6.2")])


class NotOffered(unittest.TestCase):
    def test_odd_node_lines_are_not_reported_as_new(self):
        plan = watch.make_plan(
            index={"node": ["24.19.0"]}, upstream={"node": ["24.19.0", "25.9.0", "26.10.0"]},
            tags={}, failures={},
        )
        self.assertEqual(plan.new_lines, [("node", "26")])

    def test_other_kinds_keep_every_line(self):
        plan = watch.make_plan(
            index={"go": ["1.27.1"]}, upstream={"go": ["1.27.1", "1.28.0", "1.29.0"]},
            tags={}, failures={},
        )
        self.assertEqual(plan.new_lines, [("go", "1.28"), ("go", "1.29")])


if __name__ == "__main__":
    unittest.main()
