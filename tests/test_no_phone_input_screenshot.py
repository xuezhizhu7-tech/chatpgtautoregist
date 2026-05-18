import unittest
from pathlib import Path


REGISTER_PATH = Path(__file__).resolve().parents[1] / "step_04_register" / "register.py"


class NoPhoneInputScreenshotTest(unittest.TestCase):
    def test_no_phone_input_screenshot_debug_removed(self):
        source = REGISTER_PATH.read_text()
        self.assertNotIn("worker_logs\" / \"screenshots", source)
        self.assertNotIn("await cdp.screenshot", source)
        self.assertNotIn("截图:", source)


if __name__ == "__main__":
    unittest.main()
