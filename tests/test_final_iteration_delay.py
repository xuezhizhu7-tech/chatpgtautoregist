import unittest
from pathlib import Path


REGISTER_PATH = Path(__file__).resolve().parents[1] / "step_04_register" / "register.py"


class FinalIterationDelayTest(unittest.TestCase):
    def setUp(self):
        self.source = REGISTER_PATH.read_text()

    def test_failure_delay_only_between_accounts(self):
        self.assertGreaterEqual(self.source.count("if i < target_count:"), 3)
        self.assertIn("if i < target_count:\n                delay = random.randint(10, 30)\n                log(f\"  等待 {delay} 秒后进行下一次尝试...\")", self.source)

    def test_success_delay_only_between_accounts(self):
        self.assertIn("if i < target_count:\n            delay = random.randint(15, 45)\n            log(f\"  等待 {delay} 秒后处理下一个账号...\")", self.source)


if __name__ == "__main__":
    unittest.main()
