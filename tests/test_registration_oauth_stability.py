import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "step_04_register" / "register.py"
OAUTH_PATH = ROOT / "step_05_import" / "oauth_import.py"


class RegistrationAndOAuthStabilityTest(unittest.TestCase):
    def setUp(self):
        self.register_source = REGISTER_PATH.read_text()
        self.oauth_source = OAUTH_PATH.read_text()

    def test_about_you_finish_retries_before_classifying_failure(self):
        source = self.register_source
        self.assertIn("for finish_attempt in range(1, 4):", source)
        self.assertIn("重新点击完成帐户创建", source)
        self.assertIn("about-you 最终仍未通过", source)
        self.assertIn("Finish creating account", source)

    def test_oauth_phone_submit_logs_visible_hidden_and_button_state(self):
        source = self.oauth_source
        self.assertIn("手机号提交前复查", source)
        self.assertIn("renderedValue", source)
        self.assertIn("hidden", source)
        self.assertIn("submitButton", source)
        self.assertIn("local_phone", source)

    def test_oauth_email_verification_logs_displayed_email_match(self):
        source = self.oauth_source
        self.assertIn("验证码页显示邮箱", source)
        self.assertIn("emailMatches", source)
        self.assertIn("account_email", source)

    def test_oauth_consent_uses_request_submit_before_click_fallback(self):
        source = self.oauth_source
        self.assertIn("trigger_consent_continue", source)
        self.assertIn("requestSubmit", source)
        self.assertIn("consent_attempt in range(1, 6)", source)
        self.assertIn("clicked:last", source)


if __name__ == "__main__":
    unittest.main()
