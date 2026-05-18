import unittest
from pathlib import Path


REGISTER_PATH = Path(__file__).resolve().parents[1] / "step_04_register" / "register.py"


class RegisterDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.source = REGISTER_PATH.read_text()

    def _missing_phone_block(self):
        start = self.source.index("if not has_tel:")
        end = self.source.index("url = await cdp.url()", start)
        return self.source[start:end]

    def test_missing_phone_input_is_recorded_without_verbose_debug(self):
        block = self._missing_phone_block()
        self.assertNotIn("log-in-or-create-account?usernameKind=phone_number", block)
        self.assertNotIn("尝试直接打开手机号注册地址", block)
        self.assertNotIn("log_page_diagnostics(cdp, \"2e\"", block)
        self.assertIn("记录 no_phone_input 并跳过本次号码", block)
        self.assertIn('"status": "no_phone_input"', block)
        self.assertIn("cancel_number", block)

    def test_contact_verification_failure_still_logs_diagnostics(self):
        self.assertIn("contact-verification", self.source)
        self.assertIn("log_page_diagnostics(cdp, \"7e\", \"短信验证码提交后仍停留在验证页\")", self.source)
        self.assertRegex(self.source, r"if \"contact-verification\" in \(url or \"\"\):\n\s+await log_page_diagnostics")


if __name__ == "__main__":
    unittest.main()
