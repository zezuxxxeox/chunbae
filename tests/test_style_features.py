import unittest

from style_features import extract_style_features


class StyleFeatureTests(unittest.TestCase):
    def test_counts_punctuation_and_hanja(self):
        records = [
            {"text": "건강(健康)이 최고야. 무리하지 마라 ."},
            {"text": "내가 해보니 기본(基本)이 중요한 겁니다. 그게 맞습니다."},
        ]
        summary = extract_style_features(records)
        self.assertEqual(summary.document_count, 2)
        self.assertGreaterEqual(summary.period_count, 3)
        self.assertGreaterEqual(summary.hanja_pair_count, 2)
        self.assertGreaterEqual(summary.space_before_punctuation_count, 1)

    def test_detects_experience_expression(self):
        records = [{"text": "내가 해보니 사람 사는 게 다 그렇지."}]
        summary = extract_style_features(records)
        self.assertGreaterEqual(summary.experience_expression_count, 1)

    def test_empty_records(self):
        summary = extract_style_features([])
        self.assertEqual(summary.document_count, 0)
        self.assertEqual(summary.avg_text_length, 0.0)


if __name__ == "__main__":
    unittest.main()
