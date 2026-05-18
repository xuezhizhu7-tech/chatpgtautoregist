import unittest
from pathlib import Path


OAUTH_PATH = Path(__file__).resolve().parents[1] / "step_05_import" / "oauth_import.py"


class OAuthFinalIterationDelayTest(unittest.TestCase):
    def setUp(self):
        self.source = OAUTH_PATH.read_text()

    def test_oauth_delay_only_between_accounts(self):
        self.assertIn("if i < len(pending):\n            delay = random.randint(15, 45)\n            log(f\"  等待 {delay} 秒后处理下一个账号...\")", self.source)
        tail = self.source[self.source.index("# Random delay between accounts"):self.source.index("summary =", self.source.index("# Random delay between accounts"))]
        self.assertNotIn("delay = random.randint(15, 45)\n        log", tail)


if __name__ == "__main__":
    unittest.main()
