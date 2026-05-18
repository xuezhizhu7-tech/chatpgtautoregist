import importlib
import os
import unittest


REQUIRED_SECRET_ENV = {
    "HEROSMS_KEY": "dummy",
    "SUB2API_EMAIL": "dummy@example.com",
    "SUB2API_PASS": "dummy",
    "CLOUD_MAIL_EMAIL": "dummy@example.com",
    "CLOUD_MAIL_PASS": "dummy",
    "EMAIL_DOMAIN": "example.com",
}


class BrowserConfigTest(unittest.TestCase):
    def setUp(self):
        self._old_env = os.environ.copy()
        os.environ.update(REQUIRED_SECRET_ENV)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def reload_config(self):
        import step_01_config.config as config
        return importlib.reload(config)

    def test_default_browser_is_google_chrome_stable(self):
        os.environ.pop("BROWSER", None)
        os.environ.pop("BROWSER_PATH", None)
        os.environ.pop("BROWSER_VERSION", None)
        os.environ.pop("BROWSER_MAJOR_VERSION", None)
        config = self.reload_config()

        self.assertEqual(config.BROWSER, "google-chrome-stable")
        self.assertEqual(config.BROWSER_PATH, "/usr/bin/google-chrome-stable")
        self.assertEqual(config.BROWSER_PROCESS_PATTERN, "(chromium|chrome)")
        self.assertTrue(config.BROWSER_MAJOR_VERSION.isdigit())
        self.assertTrue(all(f"Chrome/{config.BROWSER_MAJOR_VERSION}.0.0.0" in ua for ua in config.USER_AGENTS))

    def test_can_switch_to_snap_chromium(self):
        os.environ["BROWSER"] = "chromium-snap"
        os.environ.pop("BROWSER_PATH", None)
        config = self.reload_config()

        self.assertEqual(config.BROWSER, "chromium-snap")
        self.assertEqual(config.BROWSER_PATH, "/snap/bin/chromium")
        self.assertEqual(config.BROWSER_PROCESS_PATTERN, "(chromium|chrome)")

    def test_browser_path_override_keeps_selected_name(self):
        os.environ["BROWSER"] = "google-chrome-stable"
        os.environ["BROWSER_PATH"] = "/custom/chrome"
        config = self.reload_config()

        self.assertEqual(config.BROWSER, "google-chrome-stable")
        self.assertEqual(config.BROWSER_PATH, "/custom/chrome")

    def test_browser_version_override_controls_user_agent_major(self):
        os.environ["BROWSER"] = "google-chrome-stable"
        os.environ["BROWSER_VERSION"] = "148.0.7778.167"
        os.environ.pop("BROWSER_MAJOR_VERSION", None)
        config = self.reload_config()

        self.assertEqual(config.BROWSER_VERSION, "148.0.7778.167")
        self.assertEqual(config.BROWSER_MAJOR_VERSION, "148")
        self.assertTrue(all("Chrome/148.0.0.0" in ua for ua in config.USER_AGENTS))


if __name__ == "__main__":
    unittest.main()
