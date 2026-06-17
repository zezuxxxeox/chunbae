"""Fixed portfolio answers.

These are not a fallback generator. They are intentional, editable portfolio
answers that still pass through the character styling layer before display.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PORTFOLIO_PATH = Path(__file__).resolve().parent / "portfolio_answers.json"


@dataclass(frozen=True)
class PortfolioAnswer:
    id: str
    triggers: tuple[str, ...]
    keywords: tuple[str, ...]
    answer: str
    enabled: bool = True


class PortfolioAnswerBook:
    def __init__(self, path: str | Path = DEFAULT_PORTFOLIO_PATH, answers: list[PortfolioAnswer] | None = None):
        self.path = Path(path)
        self.answers = answers if answers is not None else self._load()

    @classmethod
    def from_items(cls, items: list[dict]) -> "PortfolioAnswerBook":
        return cls(answers=[_parse_answer(item) for item in items])

    def find(self, message: str) -> str | None:
        compact_message = _compact(message)
        if not compact_message:
            return None

        best_score = 0
        best_answer: str | None = None
        for item in self.answers:
            if not item.enabled or not item.answer.strip():
                continue
            score = _score_answer(item, compact_message)
            if score > best_score:
                best_score = score
                best_answer = item.answer
        return best_answer if best_score >= 8 else None

    def match_debug(self, message: str) -> list[tuple[str, int]]:
        compact_message = _compact(message)
        scores = [(item.id, _score_answer(item, compact_message)) for item in self.answers if item.enabled]
        return sorted(scores, key=lambda pair: pair[1], reverse=True)

    def _load(self) -> list[PortfolioAnswer]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        return [_parse_answer(item) for item in raw if isinstance(item, dict)]


def _score_answer(item: PortfolioAnswer, compact_message: str) -> int:
    if not compact_message:
        return 0

    matched_triggers: set[str] = set()
    for trigger in item.triggers:
        compact_trigger = _compact(trigger)
        if not compact_trigger:
            continue
        if compact_trigger == compact_message:
            matched_triggers.add(compact_trigger)
            continue
        if compact_trigger in compact_message:
            matched_triggers.add(compact_trigger)
            continue
        similarity = _similarity(compact_message, compact_trigger)
        if similarity >= 0.72:
            matched_triggers.add(compact_trigger)

    score = 0
    for trigger in matched_triggers:
        if any(trigger != other and trigger in other for other in matched_triggers):
            continue
        if trigger == compact_message:
            score += 1000
        elif trigger in compact_message:
            score += 20 + len(trigger)
        else:
            score += 12

    matched_keywords: set[str] = set()
    for keyword in item.keywords:
        compact_keyword = _compact(keyword)
        if compact_keyword and compact_keyword in compact_message:
            matched_keywords.add(compact_keyword)

    for keyword in matched_keywords:
        if any(keyword != other and keyword in other for other in matched_keywords):
            continue
        score += 5 if len(keyword) >= 3 else 3

    concept_hits = _concept_hits(compact_message)
    score += sum(_CONCEPT_WEIGHTS.get(item.id, {}).get(hit, 0) for hit in concept_hits)
    return score


def _parse_answer(item: dict) -> PortfolioAnswer:
    triggers = item.get("triggers", [])
    if not isinstance(triggers, list):
        triggers = []
    keywords = item.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    return PortfolioAnswer(
        id=str(item.get("id", "")),
        triggers=tuple(str(trigger) for trigger in triggers),
        keywords=tuple(str(keyword) for keyword in keywords),
        answer=str(item.get("answer", "")),
        enabled=bool(item.get("enabled", True)),
    )


def _compact(text: str) -> str:
    compact = "".join(str(text or "").lower().split())
    for alias, canonical in _ALIASES:
        compact = compact.replace(alias, canonical)
    return compact


def _concept_hits(compact_message: str) -> set[str]:
    hits: set[str] = set()
    for concept, terms in _CONCEPT_TERMS.items():
        if any(term in compact_message for term in terms):
            hits.add(concept)
    return hits


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))

    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    distance = previous[-1]
    return 1.0 - (distance / max(len(left), len(right)))


_ALIASES = (
    ("포폴", "포트폴리오"),
    ("프로필", "포트폴리오"),
    ("작품", "작업물"),
    ("작업목록", "작업물"),
    ("대표작업", "대표작"),
    ("대표프로젝트", "대표작"),
    ("세개", "3개"),
    ("세가지", "3개"),
    ("세가지만", "3개"),
    ("기술스텍", "기술스택"),
    ("기술스택", "기술스택"),
    ("테크스택", "기술스택"),
    ("ai에이전트", "ai에이전트"),
    ("aiagent", "ai에이전트"),
    ("깃헙", "github"),
    ("깃허브", "github"),
    ("지메일", "이메일"),
)


_CONCEPT_TERMS = {
    "overview": ("포트폴리오", "요약", "소개", "누구", "한눈", "전체", "3문장"),
    "projects": ("대표작", "프로젝트", "작업물", "결과물", "만든것", "3개", "뭐있"),
    "copy": ("카피", "문구", "문장", "광고", "댓글", "재치", "말맛", "아재개그", "네이밍"),
    "stack": ("기술스택", "스택", "사용기술", "개발환경", "스킬", "역량", "python", "분석"),
    "experience": ("경험", "경력", "실무", "니토리", "lg", "dx스쿨", "활동"),
    "fit": ("네이버", "ai에이전트", "ai", "에이전트", "지원동기", "어울려", "왜맞", "핏", "fit"),
    "agent_plan": ("캐릭터", "챗봇기획", "어떻게기획", "에이전트설계", "박춘배", "페르소나", "토큰"),
    "contact": ("연락", "이메일", "메일", "github", "링크", "사이트", "주소"),
}


_CONCEPT_WEIGHTS = {
    "portfolio_overview": {"overview": 8, "projects": 2, "copy": 1, "stack": 1, "experience": 1},
    "portfolio_projects": {"projects": 10, "overview": 1},
    "portfolio_copy": {"copy": 10, "overview": 1},
    "portfolio_stack": {"stack": 9},
    "portfolio_experience_stack": {"experience": 7, "stack": 7},
    "portfolio_experience": {"experience": 10},
    "portfolio_fit": {"fit": 12, "copy": 2, "stack": 2, "overview": 1},
    "agent_character_plan": {"agent_plan": 12, "fit": 4, "overview": 1},
    "portfolio_contact": {"contact": 10},
}
