import unittest

from prompt_builder import build_system_prompt


class PromptBuilderTests(unittest.TestCase):
    def test_contains_persona_and_safety(self):
        prompt = build_system_prompt(3)
        self.assertIn("박춘배", prompt)
        self.assertIn("가상의 캐릭터", prompt)
        self.assertIn("혐오", prompt)
        self.assertIn("개인정보", prompt)

    def test_no_legacy_persona_leftovers(self):
        prompt = build_system_prompt(3)
        for leftover in ["제성우", "우짜노"]:
            self.assertNotIn(leftover, prompt)

    def test_style_is_fixed_at_max(self):
        self.assertIn("[내부 스타일 강도] 5", build_system_prompt(1))
        self.assertIn("[내부 스타일 강도] 5", build_system_prompt(5))

    def test_prompt_prioritizes_direct_answer_and_no_meta(self):
        prompt = build_system_prompt(5)
        self.assertIn("질문 주제에 바로 답한다", prompt)
        self.assertIn("영어 메타 설명", prompt)
        self.assertIn("이모지", prompt)
        self.assertIn("그게누군데", prompt)


if __name__ == "__main__":
    unittest.main()
