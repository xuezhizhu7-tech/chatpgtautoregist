import unittest
from pathlib import Path


REGISTER_PATH = Path(__file__).resolve().parents[1] / "step_04_register" / "register.py"


class CookieBannerDismissalTest(unittest.TestCase):
    def setUp(self):
        self.source = REGISTER_PATH.read_text()

    def test_cookie_banner_dismissal_exists(self):
        start = self.source.index("async def dismiss_cookie_banner")
        end = self.source.index("async def ensure_phone_input", start)
        block = self.source[start:end]
        self.assertIn("reject non-essential", block.lower())
        self.assertIn("accept all", block.lower())
        self.assertIn("已关闭 Cookie 弹窗", block)

    def test_cookie_banner_dismissed_before_inline_auth_detection(self):
        dismiss_idx = self.source.index("await dismiss_cookie_banner(cdp)")
        detect_idx = self.source.index("# Detect UI type and navigate to phone registration")
        self.assertLess(dismiss_idx, detect_idx)


if __name__ == "__main__":
    unittest.main()
