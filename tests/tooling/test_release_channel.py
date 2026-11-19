import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import release_channel


class ReleaseChannelTests(unittest.TestCase):
    def setUp(self):
        release_channel.forget_channel()
        self.addCleanup(release_channel.forget_channel)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def stamp(self, body):
        path = Path(self.tmp.name) / ("stamp-" + str(len(list(Path(self.tmp.name).iterdir()))) + ".json")
        path.write_text(body if isinstance(body, str) else json.dumps(body))
        return path

    def test_channel_comes_from_the_deploy_stamp(self):
        self.assertEqual(release_channel.channel(self.stamp({"channel": "production"})), "production")
        self.assertEqual(release_channel.channel(self.stamp({"channel": "preview"})), "preview")
        # Stamps from before the channel existed, broken files and local development.
        self.assertEqual(release_channel.channel(self.stamp({"source_revision": "abc"})), "")
        self.assertEqual(release_channel.channel(self.stamp("not json")), "")
        self.assertEqual(release_channel.channel(self.stamp({"channel": 1})), "")
        self.assertEqual(release_channel.channel(Path(self.tmp.name) / "missing.json"), "")

    def test_production_ignores_every_test_setting(self):
        production = self.stamp({"channel": "production"})
        preview = self.stamp({"channel": "preview"})
        env = {"MLOCAL_SHOW_SAMPLES": "1", "MLOCAL_DEMO_MODE": "1", "MLOCAL_DEMO_COMPANIES": "30",
               "MLOCAL_DEMO_STUDENTS": '["0f8e"]', "MLOCAL_HOSTED_DATASET": "1"}
        with patch.dict("os.environ", env):
            for name in release_channel.TEST_SETTINGS:
                self.assertEqual(release_channel.demo_setting(name, stamp=production), "")
                self.assertEqual(release_channel.demo_setting(name, "[]", stamp=production), "[]")
                self.assertEqual(release_channel.demo_setting(name, stamp=preview), env[name])
            self.assertEqual(release_channel.ignored_test_settings(stamp=production), list(release_channel.TEST_SETTINGS))
            self.assertEqual(release_channel.ignored_test_settings(stamp=preview), [])

    def test_switched_off_settings_are_not_reported(self):
        production = self.stamp({"channel": "production"})
        env = {"MLOCAL_SHOW_SAMPLES": "0", "MLOCAL_DEMO_STUDENTS": "[]", "MLOCAL_DEMO_MODE": "off",
               "MLOCAL_HOSTED_DATASET": "1"}
        self.assertEqual(release_channel.ignored_test_settings(env, stamp=production), ["MLOCAL_HOSTED_DATASET"])

    def test_only_listed_settings_can_be_read(self):
        with self.assertRaises(ValueError):
            release_channel.demo_setting("MLOCAL_SMTP_PASSWORD")

    def test_startup_notice_names_settings_never_values(self):
        production = self.stamp({"channel": "production"})
        with patch.object(release_channel, "STAMP", production), \
                patch.dict("os.environ", {"MLOCAL_DEMO_STUDENTS": '["secret-actor-id"]'}, clear=True), \
                patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertTrue(release_channel.production_build())
            self.assertTrue(release_channel.announce_ignored_test_settings())
        self.assertIn("ignoring test settings MLOCAL_DEMO_STUDENTS", stderr.getvalue())
        self.assertNotIn("secret-actor-id", stderr.getvalue())

    def test_preview_builds_stay_quiet(self):
        with patch.object(release_channel, "STAMP", self.stamp({"channel": "preview"})), \
                patch.dict("os.environ", {"MLOCAL_SHOW_SAMPLES": "1"}, clear=True), \
                patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(release_channel.demo_setting("MLOCAL_SHOW_SAMPLES"), "1")
            release_channel.announce_ignored_test_settings()
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
