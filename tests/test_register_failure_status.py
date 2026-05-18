import unittest
from pathlib import Path


REGISTER_PATH = Path(__file__).resolve().parents[1] / "step_04_register" / "register.py"


class RegisterFailureStatusTest(unittest.TestCase):
    def setUp(self):
        self.source = REGISTER_PATH.read_text()

    def test_no_phone_input_returns_recorded_failure_not_none(self):
        self.assertIn('"status": "no_phone_input"', self.source)
        self.assertIn('"status": "no_phone_input", "recorded": True', self.source)
        self.assertNotIn('注册失败（未买到号码）', self.source)

    def test_buy_number_failed_has_explicit_status(self):
        self.assertIn('"status": "buy_number_failed", "recorded": True', self.source)

    def test_no_return_none_remains_in_register_flow(self):
        self.assertNotIn('return None', self.source)


if __name__ == "__main__":
    unittest.main()
