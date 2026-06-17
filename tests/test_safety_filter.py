import unittest

from safety_filter import SafetyFilter


class SafetyFilterTests(unittest.TestCase):
    def setUp(self):
        self.filter = SafetyFilter()

    def test_blocks_threat_request(self):
        self.assertTrue(self.filter.is_blocked_user_request("저 사람 죽여버리고 싶다"))

    def test_allows_normal_request(self):
        self.assertFalse(self.filter.is_blocked_user_request("운동 어떻게 시작하지"))

    def test_masks_email_and_phone_in_output(self):
        result = self.filter.sanitize("연락은 hong@test.com 010-1234-5678 로 해라")
        self.assertNotIn("hong@test.com", result.text)
        self.assertNotIn("010-1234-5678", result.text)
        self.assertIn("pii", result.flags)

    def test_masks_account_number(self):
        result = self.filter.sanitize("입금은 110-234-567890 계좌로")
        self.assertNotIn("110-234-567890", result.text)

    def test_redacts_excessive_profanity(self):
        result = self.filter.sanitize("씨발 진짜 병신 같네")
        self.assertIn("excessive_profanity", result.flags)
        self.assertIn("[욕설]", result.text)

    def test_does_not_filter_hechiuda(self):
        result = self.filter.sanitize("그를 해치우다")
        self.assertEqual("그를 해치우다", result.text)
        self.assertNotIn("threat", result.flags)


if __name__ == "__main__":
    unittest.main()
