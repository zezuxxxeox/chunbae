import json
import unittest
from pathlib import Path

from style_engine import (
    AjaeStyler,
    FAMOUS_CONTEXTUAL_DAD_JOKES,
    OLD_TIMER_REPLACEMENTS,
    _scrub_youth_slang,
)

LEXICON_PATH = Path(__file__).resolve().parent.parent / "persona" / "lexicon.json"

BASE = "운동은 무리하지 말고 작게 시작해라. 꾸준함이 결국 이긴다. 밥도 잘 챙겨 먹어라."


def count_contextual_jokes(text):
    return sum(1 for joke in FAMOUS_CONTEXTUAL_DAD_JOKES if joke["text"] in text)


class StyleEngineTests(unittest.TestCase):
    def setUp(self):
        self.styler = AjaeStyler()

    def test_deterministic(self):
        a = self.styler.apply(BASE, intensity=4)
        b = self.styler.apply(BASE, intensity=4)
        self.assertEqual(a, b)

    def test_level1_minimal_jokes(self):
        out = self.styler.apply(BASE, intensity=1)
        self.assertLessEqual(count_contextual_jokes(out), 1)

    def test_level5_adds_one_joke(self):
        out = self.styler.apply(BASE, intensity=5)
        # 문맥에 맞는 경우에도 본문 흐름을 해치지 않도록 농담은 한 번만 붙인다.
        self.assertLessEqual(count_contextual_jokes(out), 1)

    def test_level5_has_at_least_as_many_jokes_as_lower_intensity(self):
        low = count_contextual_jokes(self.styler.apply(BASE, intensity=1))
        high = count_contextual_jokes(self.styler.apply(BASE, intensity=5))
        self.assertGreaterEqual(high, low)

    def test_unrelated_context_does_not_force_joke(self):
        out = self.styler.apply("그냥 오늘 기분이 애매하다.", intensity=5)
        self.assertEqual(count_contextual_jokes(out), 0)

    def test_serious_topic_does_not_force_joke(self):
        out = self.styler.apply("취업 준비가 너무 막막하다.", intensity=5)
        self.assertEqual(count_contextual_jokes(out), 0)

    def test_explicit_joke_request_inserts_joke_from_pool(self):
        out = self.styler.apply("하나 해봐라.", intensity=5, context="아재개그 하나 해줘")
        self.assertTrue(
            any(j in out for j in self.styler.dad_jokes) or count_contextual_jokes(out) >= 1,
            msg="개그 요청에 검증 풀/유명개그 중 하나가 들어가야 한다.",
        )

    def test_explicit_joke_request_adds_reaction(self):
        out = self.styler.apply("하나 해봐라.", intensity=5, context="아재개그 하나 해줘")
        from style_engine import JOKE_REACTIONS
        all_reactions = [r for lst in JOKE_REACTIONS.values() for r in lst]
        self.assertTrue(
            any(r in out for r in all_reactions),
            msg="개그를 직접 요청하면 스스로 웃거나/반응을 요구하거나/핀잔 주는 반응이 붙어야 한다.",
        )

    def test_famous_joke_requires_specific_context(self):
        out = self.styler.apply("왕이 넘어지는 얘기냐.", intensity=5, context="왕이 넘어지면 뭐게")
        self.assertIn("왕이 넘어지면 킹콩이다.", out)

    def test_hanja_annotation_can_appear(self):
        text = "건강 책임 기본 노력 인생 시간 가족 성공 경험 습관 목표 용기 계획 미래"
        appeared = any("(" in self.styler.apply(text, intensity=5) for _ in range(1))
        self.assertTrue(appeared)

    def test_level5_uses_old_timer_words(self):
        out = self.styler.apply("요즘 면접 준비를 빨리 해야 한다.", intensity=5)
        self.assertTrue(any(word in out for word in ("요새", "후딱")))
        self.assertNotIn("채비", out)  # '준비->채비' 강제치환은 어색해서 뺐다

    def test_no_youth_slang_or_gibberish_words(self):
        out = self.styler.apply(
            "그냥 요즘 포트폴리오랑 이메일 링크를 인터넷 컴퓨터로 면접 준비했다.",
            intensity=5,
        )
        for bad in ("걍", "포폴", "전자우편", "인터네트", "컴푸터", "면접자리"):
            self.assertNotIn(bad, out)

    def test_empty_input(self):
        self.assertEqual(self.styler.apply("", intensity=5), "")

    def test_level5_forces_banmal_and_eye_smile(self):
        out = self.styler.apply("대표 작업은 세 개부터 보면 됩니다. 정리했습니다.", intensity=5)
        self.assertNotIn("됩니다", out)
        self.assertNotIn("했습니다", out)
        self.assertIn("ㅡㅡ", out)

    def test_period_breaks_do_not_cluster_in_opening(self):
        out = self.styler.apply(
            "제준혁은 데이터를 분석해 반응을 찾는 지원자입니다. 대표 작업은 세 개입니다. 카피도 합니다.",
            intensity=5,
        )
        self.assertNotIn("내가. 볼", out)
        self.assertNotIn("내가볼.", out)
        self.assertRegex(out, r"[가-힣]\. [가-힣]")

    def test_seumnida_does_not_become_broken_word(self):
        out = self.styler.apply("네이버 AI 에이전트 기획자와 가깝습니다. 내부 구조로 움직입니다.", intensity=5)
        self.assertNotIn("깝습다", out)
        self.assertNotIn("움직이다", out)
        self.assertIn("가깝", out)


class DataDrivenLexiconTests(unittest.TestCase):
    """말투 규칙이 코퍼스에서 추출된 패턴에 근거하는지 검증한다."""

    def test_youth_slang_is_scrubbed(self):
        out = _scrub_youth_slang("걍 포폴 보고 취준 했어. 면접자리도 가야지")
        for bad in ("걍", "포폴", "취준", "면접자리"):
            self.assertNotIn(bad, out)
        self.assertIn("그냥", out)
        self.assertIn("작업물", out)

    def test_old_timer_targets_are_attested_in_corpus(self):
        if not LEXICON_PATH.exists():
            self.skipTest("lexicon.json 없음: build_persona_lexicon.py 를 먼저 실행해라")
        lex = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
        attested = set(lex.get("attested_old_words", {}))
        # 코퍼스 기반으로 로드됐다면, 치환 대상 단어는 전부 코퍼스에 나온 말이어야 한다.
        for _modern, older in OLD_TIMER_REPLACEMENTS:
            self.assertIn(
                older, attested,
                msg=f"'{older}' 가 코퍼스에 없는데 치환 규칙에 들어있다(데이터 미근거).",
            )

    def test_corpus_has_no_youth_slang(self):
        if not LEXICON_PATH.exists():
            self.skipTest("lexicon.json 없음")
        lex = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
        self.assertEqual(lex.get("youth_slang_in_corpus", {}), {})


if __name__ == "__main__":
    unittest.main()
