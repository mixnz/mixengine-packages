import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import upstream  # noqa: E402


class Parsers(unittest.TestCase):
    def test_php_drops_release_candidates(self):
        docs = [{"8.5.11": {}, "8.5.10": {}, "8.6.0RC1": {}}, {"7.4.33": {}}]
        self.assertEqual(sorted(upstream.from_php(docs)), ["7.4.33", "8.5.10", "8.5.11"])

    def test_node_strips_v_and_drops_prereleases(self):
        entries = [{"version": "v22.24.0"}, {"version": "v23.0.0-rc.1"}]
        self.assertEqual(upstream.from_node(entries), ["22.24.0"])

    def test_go_keeps_stable_three_part_only(self):
        entries = [
            {"version": "go1.27.2", "stable": True},
            {"version": "go1.28rc1", "stable": False},
            {"version": "go1.28.0", "stable": False},
        ]
        self.assertEqual(upstream.from_go(entries), ["1.27.2"])

    def test_github_drops_drafts_prereleases_and_odd_tags(self):
        releases = [
            {"tag_name": "v2.12.0", "draft": False, "prerelease": False},
            {"tag_name": "v2.13.0-beta.1", "draft": False, "prerelease": True},
            {"tag_name": "v2.12.1", "draft": True, "prerelease": False},
            {"tag_name": "nightly", "draft": False, "prerelease": False},
            {"tag_name": "2.10.4", "draft": False, "prerelease": False},
        ]
        self.assertEqual(sorted(upstream.from_github(releases)), ["2.10.4", "2.12.0"])

    def test_ruby_index_drops_previews_and_non_tarballs(self):
        text = (
            "name\turl\tsha1\tsha256\tsha512\n"
            "ruby-3.4.10\thttps://x/ruby-3.4.10.tar.gz\ta\tb\tc\n"
            "ruby-3.4.10\thttps://x/ruby-3.4.10.zip\ta\tb\tc\n"
            "ruby-4.1.0-preview1\thttps://x/ruby-4.1.0-preview1.tar.gz\ta\tb\tc\n"
        )
        self.assertEqual(upstream.from_ruby_index(text), ["3.4.10"])

    def test_python_reads_versions_off_asset_names(self):
        names = [
            "cpython-3.14.7+20260920-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
            "cpython-3.15.0rc1+20260920-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
            "cpython-3.13.15+20260920-aarch64-apple-darwin-install_only_stripped.tar.gz",
        ]
        self.assertEqual(
            sorted(upstream.from_python_sums(names, "20260920")), ["3.13.15", "3.14.7"]
        )

    def test_mongodb_keeps_production_releases(self):
        records = [
            {"version": "8.0.33", "production_release": True},
            {"version": "8.3.0-rc2", "production_release": False},
        ]
        self.assertEqual(upstream.from_mongodb(records), ["8.0.33"])

    def test_rubyinstaller_versions_come_from_its_tags(self):
        releases = [
            {"tag_name": "RubyInstaller-4.0.7-1", "draft": False, "prerelease": False},
            {"tag_name": "RubyInstaller-4.1.0-preview1-1", "draft": False, "prerelease": True},
            {"tag_name": "RubyInstaller-3.4.10-2", "draft": False, "prerelease": False},
        ]
        self.assertEqual(sorted(upstream.from_rubyinstaller(releases)), ["3.4.10", "4.0.7"])

    def test_ruby_waits_for_rubyinstaller(self):
        self.assertEqual(upstream.ruby_both(["4.0.6", "4.0.7"], ["4.0.6"]), ["4.0.6"])

    def test_every_watchable_kind_is_known(self):
        for kind in ("php", "node", "python", "ruby", "go", "java", "caddy", "composer",
                     "mongosh", "memcached", "nginx", "httpd", "redis", "valkey", "mariadb",
                     "mysql", "postgres", "mongodb"):
            self.assertIn(kind, upstream.KINDS)
        self.assertNotIn("meilisearch", upstream.KINDS)


if __name__ == "__main__":
    unittest.main()
