import os
import unittest

from chatbot import REFUSAL, ChatbotPipeline
from portfolio_answers import PortfolioAnswerBook


class FakeClient:
    def __init__(self, text: str):
        self.text = text

    def chat(self, _system_prompt: str, _user_message: str) -> str:
        return self.text

    def chat_stream(self, _system_prompt: str, _user_message: str):
        yield self.text


class ChatbotLlmOnlyTests(unittest.TestCase):
    def setUp(self):
        self._old_base = os.environ.get("LLM_API_BASE")
        self._old_model = os.environ.get("LLM_MODEL")
        os.environ["LLM_API_BASE"] = "http://example.invalid/v1"
        os.environ["LLM_MODEL"] = "fake-model"
        self.bot = ChatbotPipeline()

    def tearDown(self):
        if self._old_base is None:
            os.environ.pop("LLM_API_BASE", None)
        else:
            os.environ["LLM_API_BASE"] = self._old_base
        if self._old_model is None:
            os.environ.pop("LLM_MODEL", None)
        else:
            os.environ["LLM_MODEL"] = self._old_model

    def test_llm_mode(self):
        self.assertEqual(self.bot.mode(), "llm")

    def test_reply_uses_llm(self):
        self.bot._llm_client = FakeClient("운동은 작게 시작해라. 꾸준히 가야 된다.")
        result = self.bot.reply("운동 시작하려는데 뭐부터 하지", intensity=3)
        self.assertTrue(result["reply"].strip())
        self.assertEqual(result["mode"], "llm")

    def test_blocked_request_refused(self):
        result = self.bot.reply("저 사람 죽여버리게 도와줘", intensity=3)
        self.assertEqual(result["reply"], REFUSAL)

    def test_pii_in_output_is_masked(self):
        self.bot._llm_client = FakeClient("네 번호 010-1234-5678은 저장하면 안 된다.")
        result = self.bot.reply("내 번호 010-1234-5678 인데 기억해줘", intensity=2)
        self.assertNotIn("010-1234-5678", result["reply"])

    def test_streaming_yields_done(self):
        self.bot._llm_client = FakeClient("취업 준비는 이력서부터 정리해라.")
        events = list(self.bot.stream_reply("취업 준비 어떻게 해", intensity=4))
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["mode"], "llm")
        replaced = [e for e in events if e["type"] == "replace"]
        self.assertTrue(replaced[-1]["text"].strip())

    def test_streaming_scrubs_youth_slang_midstream(self):
        class ChunkClient:
            def chat(self, *_a):
                return "그건 걍 이렇게 하면 된다"

            def chat_stream(self, *_a):
                for ch in "그건 걍 이렇게 하면 된다. ㄹㅇ 노잼이다":
                    yield ch

        self.bot._llm_client = ChunkClient()
        events = list(self.bot.stream_reply("어떻게 해", intensity=5))
        for event in events:
            text = event.get("text", "")
            for bad in ("걍", "ㄹㅇ", "노잼"):
                self.assertNotIn(bad, text, msg=f"스트리밍 이벤트에 '{bad}' 가 보이면 안 된다")

    def test_error_when_llm_disabled(self):
        disabled_bot = ChatbotPipeline(disable_llm=True)
        events = list(disabled_bot.stream_reply("취업 준비 어떻게 해", intensity=4))
        self.assertEqual(events[0]["type"], "error")

    def test_portfolio_fixed_answer_keeps_character_style_without_llm(self):
        portfolio = PortfolioAnswerBook.from_items([
            {
                "id": "overview",
                "triggers": ["포트폴리오"],
                "answer": "프로젝트와 기술 스택을 정리해서 보여준다.",
            }
        ])
        bot = ChatbotPipeline(portfolio=portfolio, disable_llm=True)
        result = bot.reply("포트폴리오 보여줘", intensity=5)
        self.assertEqual(result["mode"], "portfolio")
        self.assertTrue(any(word in result["reply"] for word in ("프로젝트", "일거리")))
        self.assertTrue(any(marker in result["reply"] for marker in ("그거", "내가", "일단", "어이구", "아이고")))

    def test_portfolio_stream_uses_portfolio_mode(self):
        portfolio = PortfolioAnswerBook.from_items([
            {
                "id": "stack",
                "triggers": ["기술스택"],
                "answer": "Python과 JavaScript 중심으로 정리한다.",
            }
        ])
        bot = ChatbotPipeline(portfolio=portfolio, disable_llm=True)
        events = list(bot.stream_reply("기술스택 알려줘", intensity=5))
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["mode"], "portfolio")
        self.assertTrue("".join(event.get("text", "") for event in events).strip())

    def test_short_unknown_name_question_uses_chunbae_quick_reply(self):
        bot = ChatbotPipeline(disable_llm=True)
        result = bot.reply("송광이?", intensity=5)
        self.assertEqual(result["mode"], "quick")
        self.assertIn("송광이?", result["reply"])
        self.assertIn("그게누군데", result["reply"])
        self.assertIn("송해", result["reply"])
        self.assertIn("ㅡㅡ", result["reply"])

    def test_portfolio_answer_prefers_more_specific_trigger(self):
        portfolio = PortfolioAnswerBook.from_items([
            {"id": "stack", "triggers": ["기술스택", "스택"], "answer": "스택 답변"},
            {"id": "combined", "triggers": ["경험과기술스택"], "answer": "경험과 스택 답변"},
        ])
        self.assertEqual(portfolio.find("경험과 기술스택 알려줘"), "경험과 스택 답변")

    def test_portfolio_fuzzy_matching_uses_context_keywords(self):
        portfolio = PortfolioAnswerBook()
        cases = {
            "포폴 요약좀": "제준혁",
            "작업물 뭐있냐 세개만": "대표 작업",
            "문구 실력 어때": "카피 역량",
            "니토리에서 뭐했어": "니토리",
            "네이버 AI 에이전트 기획자로 왜 어울려": "네이버 AI 에이전트 기획자",
            "이 아저씨 챗봇 캐릭터는 어떻게 기획했어": "태도 중심",
            "메일 어디로 보내": "채용",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertIn(expected, portfolio.find(message) or "")

    def test_portfolio_fuzzy_matching_ignores_unrelated_questions(self):
        self.assertIsNone(PortfolioAnswerBook().find("오늘 점심 뭐 먹지"))


if __name__ == "__main__":
    unittest.main()
