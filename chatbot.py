"""챗봇 파이프라인.

흐름(요구사항의 '답 생성 방식'을 그대로 구현):

  사용자 입력
    -> Safety Filter (위협/집단비하 요청은 거절, 개인정보 마스킹)
    -> Base Answer Generator (LLM 전용, 실패하면 에러)
    -> Character Styling System (강도별 마침표/띄어쓰기/한자/아재개그)
    -> Safety Filter (출력 한 번 더 정제)
    -> 응답

LLM 에는 원문 데이터를 직접 넣지 않는다. prompt_builder 가 만든 시스템
프롬프트(학습된 '지표'만 요약) 위에서 답을 생성한다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from llm_client import LLMConfig, LLMConfigurationError, LLMRequestError, OpenAICompatibleClient
from portfolio_answers import PortfolioAnswerBook
from prompt_builder import build_system_prompt
from safety_filter import SafetyFilter
from style_engine import AjaeStyler, scrub_youth_slang


REFUSAL = (
    "그건 그대로는 못 도와준다. 사람이나 특정 집단을 해치거나 깎아내리는 쪽 말고, "
    "다른 식으로 다시 물어봐라."
)


class ChatbotPipeline:
    def __init__(
        self,
        styler: AjaeStyler | None = None,
        safety: SafetyFilter | None = None,
        portfolio: PortfolioAnswerBook | None = None,
        disable_llm: bool = False,
    ):
        self.styler = styler or AjaeStyler()
        self.safety = safety or SafetyFilter()
        self.portfolio = portfolio or PortfolioAnswerBook()
        self.llm_disabled = disable_llm
        self._llm_client: OpenAICompatibleClient | None = None

    def mode(self) -> str:
        if self.llm_disabled:
            return "llm_disabled"
        return "llm" if LLMConfig.is_configured() else "llm_unconfigured"

    # --- 비스트리밍 ---
    def reply(self, message: str, intensity: int = 5, history: list[dict] | None = None) -> dict:
        incoming = self.safety.sanitize(message)
        if self.safety.is_blocked_user_request(message):
            return self._refusal(incoming.flags)
        clean_history = _clean_history(history, self.safety)

        portfolio_answer = self.portfolio.find(incoming.text)
        if portfolio_answer:
            final = self._style_and_sanitize(portfolio_answer, intensity, incoming.text, joke_context=incoming.text)
            return {
                "reply": final.text,
                "mode": "portfolio",
                "input_flags": incoming.flags,
                "output_flags": final.flags,
            }

        quick_reply = _unknown_person_reply(incoming.text)
        if quick_reply:
            final = self.safety.sanitize(quick_reply)
            return {
                "reply": final.text,
                "mode": "quick",
                "input_flags": incoming.flags,
                "output_flags": final.flags,
            }

        try:
            base = self._generate(incoming.text, intensity, clean_history)
        except (LLMConfigurationError, LLMRequestError) as exc:
            raise LLMRequestError(f"LLM 응답 실패: {exc}") from exc
        final = self._style_and_sanitize(base, intensity, incoming.text)
        return {"reply": final.text, "mode": "llm", "input_flags": incoming.flags, "output_flags": final.flags}

    # --- 스트리밍 (웹 UI 용) ---
    def stream_reply(self, message: str, intensity: int = 5, history: list[dict] | None = None) -> Iterator[dict]:
        incoming = self.safety.sanitize(message)
        if self.safety.is_blocked_user_request(message):
            yield {"type": "replace", "text": REFUSAL}
            yield {"type": "done", "mode": self.mode(), "input_flags": incoming.flags, "output_flags": []}
            return
        clean_history = _clean_history(history, self.safety)

        portfolio_answer = self.portfolio.find(incoming.text)
        if portfolio_answer:
            final = self._style_and_sanitize(portfolio_answer, intensity, incoming.text, joke_context=incoming.text)
            for chunk in _chunk_text(final.text):
                yield {"type": "delta", "text": chunk}
            yield {
                "type": "done",
                "mode": "portfolio",
                "input_flags": incoming.flags,
                "output_flags": final.flags,
            }
            return

        quick_reply = _unknown_person_reply(incoming.text)
        if quick_reply:
            final = self.safety.sanitize(quick_reply)
            for chunk in _chunk_text(final.text):
                yield {"type": "delta", "text": chunk}
            yield {
                "type": "done",
                "mode": "quick",
                "input_flags": incoming.flags,
                "output_flags": final.flags,
            }
            return

        mode = self.mode()
        raw = ""

        if mode != "llm":
            yield {"type": "error", "error": "LLM이 꺼져 있거나 설정이 없습니다. llm.env 설정을 확인해라."}
            return

        shown = ""
        try:
            for chunk in self._llm_stream(incoming.text, intensity, clean_history):
                raw += chunk
                # 스트리밍 중간에도 '걍' 같은 젊은말이 한 글자도 안 보이게 즉시 되돌린다.
                partial = scrub_youth_slang(self.safety.sanitize(raw).text)
                if partial.startswith(shown):
                    delta = partial[len(shown):]
                else:
                    delta = partial
                    yield {"type": "replace", "text": ""}
                if delta:
                    yield {"type": "delta", "text": delta}
                    shown = partial
        except (LLMConfigurationError, LLMRequestError) as exc:
            yield {"type": "error", "error": f"LLM 응답 실패: {exc}"}
            return

        if not raw.strip():
            yield {"type": "error", "error": "LLM이 빈 응답을 반환했습니다."}
            return

        final = self._style_and_sanitize(raw, intensity, incoming.text)
        yield {"type": "replace", "text": final.text}
        yield {
            "type": "done",
            "mode": "llm",
            "input_flags": incoming.flags,
            "output_flags": final.flags,
        }

    # --- 내부 ---
    def _generate(self, message: str, intensity: int, history: list[dict]) -> str:
        if self.mode() != "llm":
            raise LLMConfigurationError("LLM 설정이 없습니다.")
        text = self._client().chat(build_system_prompt(intensity), _augment_user_message(message, history))
        if not text.strip():
            raise LLMRequestError("LLM이 빈 응답을 반환했습니다.")
        return text

    def _llm_stream(self, message: str, intensity: int, history: list[dict]) -> Iterator[str]:
        yield from self._client().chat_stream(build_system_prompt(intensity), _augment_user_message(message, history))

    def _client(self) -> OpenAICompatibleClient:
        if self._llm_client is None:
            self._llm_client = OpenAICompatibleClient()
        return self._llm_client

    def _style_and_sanitize(self, text: str, intensity: int, context: str, joke_context: str | None = None):
        styled = self.styler.apply(text, intensity, context=context, joke_context=joke_context)
        return self.safety.sanitize(styled)

    def _refusal(self, input_flags: list[str]) -> dict:
        return {"reply": REFUSAL, "mode": self.mode(), "input_flags": input_flags, "output_flags": []}


TOPIC_HINTS = [
    (("취업", "면접", "이력서", "자소서", "회사", "직장", "이직"), "취업 준비"),
    (("배고", "밥", "먹", "아침", "점심", "저녁", "허기"), "식사/음식"),
    (("운동", "헬스", "걷", "뛰", "체력", "근육"), "운동"),
    (("공부", "시험", "숙제", "암기", "책"), "공부"),
    (("연애", "고백", "데이트", "이별", "사랑"), "연애"),
    (("돈", "월급", "저축", "소비", "투자"), "돈 관리"),
]


def _clean_history(history: list[dict] | None, safety: SafetyFilter, limit: int = 12) -> list[dict]:
    if not isinstance(history, list):
        return []
    cleaned: list[dict] = []
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        content = safety.sanitize(content[:500]).text
        cleaned.append({"role": role, "content": content})
    return cleaned


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    labels = {"user": "사용자", "assistant": "박춘배"}
    lines = [f"{labels[item['role']]}: {item['content']}" for item in history]
    return "\n".join(lines)


def _augment_user_message(message: str, history: list[dict] | None = None) -> str:
    compact = (message or "").replace(" ", "")
    history_text = _format_history(history or [])
    prefix = ""
    if history_text:
        prefix = (
            "[이전 대화]\n"
            f"{history_text}\n\n"
            "위 대화를 새로고침 전까지의 맥락으로만 참고해라. 개인정보는 기억한다고 말하지 마라.\n\n"
        )
    for keywords, topic in TOPIC_HINTS:
        if any(keyword in compact for keyword in keywords):
            return (
                prefix +
                f"[주제 힌트: {topic}]\n"
                "이 주제에서 벗어나지 말고 답해라. 질문에 없는 음식/배고픔 얘기로 돌리지 마라.\n"
                f"사용자 말: {message}"
            )
    return f"{prefix}[주제 힌트: 일반 고민]\n사용자 말: {message}"


UNKNOWN_PERSON_ALIASES = {
    "송": "송해",
}


def _unknown_person_reply(message: str) -> str | None:
    raw = (message or "").strip()
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return None

    name: str | None = None
    direct = re.fullmatch(r"([가-힣]{2,4})[?？]+", compact)
    if direct and direct.group(1).endswith(("이", "가")):
        name = direct.group(1)

    asking = re.fullmatch(r"([가-힣]{2,4})(?:이|가)?(누구야?|누군데|뭐야)[?？]*", compact)
    if asking:
        name = asking.group(1)

    if not name:
        return None

    surname = name[0]
    known = UNKNOWN_PERSON_ALIASES.get(surname, f"동네 {surname}씨")
    return (
        f"일단 말이지. {name}? ㅡㅡ 그게누군데 . 내가아는  {surname}씨는 {known}밖에 없어 ㅡㅡ. "
        "괜이. 모르는사람. 찾지  말고 . 말은 말처럼 달리면 안 되고 사람 보며 해야 된다. "
        "궁금한 거 있으면 그냥 물어봐라."
    )


def _chunk_text(text: str, chunk_size: int = 6) -> Iterator[str]:
    for index in range(0, len(text), chunk_size):
        yield text[index:index + chunk_size]
