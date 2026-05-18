import unittest
from pathlib import Path


REGISTER_PATH = Path(__file__).resolve().parents[1] / "step_04_register" / "register.py"


class PhoneInputClickTimingTest(unittest.TestCase):
    def setUp(self):
        self.source = REGISTER_PATH.read_text()

    def test_first_phone_click_waits_before_verification(self):
        self.assertIn("if phone_clicked:\n                await asyncio.sleep(2)", self.source)

    def test_no_verbose_phone_option_lost_debug_logs(self):
        self.assertNotIn("phone_option_lost", self.source)
        self.assertNotIn("等待手机号输入框 attempt=", self.source)
        self.assertNotIn("连续确认手机号入口消失", self.source)


if __name__ == "__main__":
    unittest.main()
