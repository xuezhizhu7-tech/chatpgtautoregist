import unittest
from pathlib import Path


REGISTER_PATH = Path(__file__).resolve().parents[1] / "step_04_register" / "register.py"


class RegisterPhoneInputFallbackTest(unittest.TestCase):
    def test_missing_phone_input_does_not_direct_navigate_to_phone_registration(self):
        source = REGISTER_PATH.read_text()
        start = source.index("if not has_tel:")
        end = source.index("url = await cdp.url()", start)
        block = source[start:end]

        self.assertNotIn("log-in-or-create-account?usernameKind=phone_number", block)
        self.assertNotIn("尝试直接打开手机号注册地址", block)
        self.assertNotIn("log_page_diagnostics(cdp, \"2e\"", block)
        self.assertIn("记录 no_phone_input 并跳过本次号码", block)
        self.assertIn('"status": "no_phone_input"', block)
        self.assertIn("cancel_number", block)


if __name__ == "__main__":
    unittest.main()
