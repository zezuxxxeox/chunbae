"""캐릭터 스타일링 시스템.

Base Answer Generator(LLM 또는 오프라인)가 만든 '내용'에, 박춘배 캐릭터의
표면 말투를 입힌다. 내용은 건드리지 않고 표면만 바꾸는 게 원칙이다.

- 마침표를 어색/과하게
- 띄어쓰기를 덜 해서 와다다 붙여 쓰는 느낌
- 맞춤법을 가끔 발음식으로 틀림
- 한자어 가끔 병기 (건강 -> 건강(健康))
- 문맥이 맞을 때만 아재개그를 자연스럽게 삽입

강도(1~5)에 따라 정도를 조절하며, 같은 입력에는 항상 같은 결과가 나오도록
입력 텍스트 기반 시드로 난수를 고정한다(테스트와 UX 일관성).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path


PERSONA_DIR = Path(__file__).resolve().parent / "persona"
DAD_JOKES_PATH = PERSONA_DIR / "dad_jokes.json"

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。…])\s+|\n+")
EMOJI_RE = re.compile(
    "[\U0001f1e6-\U0001f1ff\U0001f300-\U0001f5ff\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff\U0001f700-\U0001f77f\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff\U0001f900-\U0001f9ff\U0001fa00-\U0001faff"
    "\u2600-\u27bf\ufe0f]+"
)

# 안전한 일상 어휘 -> 한자 병기 사전
HANJA_DICT = {
    "건강": "健康", "책임": "責任", "기본": "基本", "노력": "努力", "인생": "人生",
    "시간": "時間", "결국": "結局", "가족": "家族", "성공": "成功", "중요": "重要",
    "경험": "經驗", "사회": "社會", "공부": "工夫", "운동": "運動",
    "약속": "約束", "신뢰": "信賴", "발전": "發展", "미래": "未來", "과거": "過去",
    "부모": "父母", "자식": "子息", "행복": "幸福", "최선": "最善", "기회": "機會",
    "준비": "準備", "습관": "習慣", "용기": "勇氣", "계획": "計劃", "목표": "目標",
    "정성": "精誠", "정신": "精神", "세상": "世上", "사람": "人間",
}

# 실제로 널리 알려진 유명 아재개그만 모은 풀이다(억지 말장난/외계어 개그는 두지 않는다).
# keywords 중 min_matches 개 이상이 사용자/답변 문맥에 들어 있을 때만 그 개그가 후보가 된다.
# 한글은 받침 없는 한 글자(소, 강, 새, 비 등)가 다른 단어에 끼어드는 오탐이 잦아,
# 각 개그마다 그 개그에서만 나오는 '특정 단어'를 같이 요구해 엉뚱한 데서 안 튀게 했다.
FAMOUS_CONTEXTUAL_DAD_JOKES = [
    # --- 동물 ---
    {
        "keywords": ("왕", "임금", "넘어", "킹콩"),
        "min_matches": 2,
        "text": "왕이 넘어지면 킹콩이다.",
    },
    {
        "keywords": ("소", "노래", "소송"),
        "min_matches": 2,
        "text": "소가 노래하면 소송이다.",
    },
    {
        "keywords": ("오리", "회오리", "먹"),
        "min_matches": 2,
        "text": "오리를 생으로 먹으면 회오리다.",
    },
    {
        "keywords": ("강아지", "가르치", "개인지도"),
        "min_matches": 2,
        "text": "강아지가 사람을 가르치면 개인지도다.",
    },
    # --- 바다/날씨 ---
    {
        "keywords": ("바다", "뜨거", "더워", "열바다"),
        "min_matches": 2,
        "text": "세상에서 제일 뜨거운 바다는 열바다다.",
    },
    {
        "keywords": ("바다", "추워", "차가", "썰렁"),
        "min_matches": 2,
        "text": "세상에서 제일 추운 바다는 썰렁해다.",
    },
    # --- 과일/음식 ---
    {
        "keywords": ("바나나", "먹", "반하나"),
        "min_matches": 2,
        "text": "바나나 먹으면 나한테 반하나.",
    },
    {
        "keywords": ("딸기", "잘리", "해고", "짤", "시럽"),
        "min_matches": 2,
        "text": "딸기가 회사에서 잘리면 딸기시럽이다.",
    },
    {
        "keywords": ("라면", "맛있", "달콤", "함께라면"),
        "min_matches": 2,
        "text": "세상에서 제일 맛있는 라면은 그대와 함께라면이다.",
    },
    # --- 한글/공부 ---
    {
        "keywords": ("세종", "한글", "우유", "훈민정음"),
        "min_matches": 2,
        "text": "세종대왕이 만든 우유는 아야어여오요우유다.",
    },
]
DEFAULT_DAD_JOKES = [item["text"] for item in FAMOUS_CONTEXTUAL_DAD_JOKES]
JOKE_REQUEST_KEYWORDS = ("아재개그", "개그", "농담", "웃긴말", "웃겨", "말장난")

# 실제로 5~60대가 쓰는 발음표기/사투리만 남긴다.
# '잇다(있다)·업다(없다=업고 가다)·마따(맞다)·가따(같다)·겨(거야)·알러(알려)'처럼
# 뜻이 달라지거나 외계어로 보이는 표기는 넣지 않는다.
PHONETIC_REPLACEMENTS = [
    ("괜히", "괜이"),
    ("괜찮", "괜찬"),
    ("그렇지", "그렇치"),
    ("어차피", "어짜피"),
    ("아니야", "아녀"),
    ("말이야", "말여"),
    ("정말", "증말"),
    ("조금", "쪼금"),
    ("먹어라", "묵어라"),
    ("먹고", "묵고"),
    ("보면", "보믄"),
    ("하면", "하믄"),
    ("궁금한", "궁금헌"),
    ("궁금하", "궁금허"),
]

# 옛말투 치환은 '코퍼스에서 추출된 패턴'(persona/lexicon.json)을 우선 읽는다.
# build_persona_lexicon.py 가 수집 코퍼스에서 '실제로 나온 단어'만 골라 만든 것이라,
# 여기 목록은 임의로 적은 게 아니라 데이터로 검증된 단어다.
# lexicon.json 이 없을 때를 대비한 안전 기본값만 코드에 둔다(모두 뜻 보존, 윗세대 실사용 단어).
LEXICON_PATH = PERSONA_DIR / "lexicon.json"

FALLBACK_OLD_TIMER_REPLACEMENTS = [
    ("요즘", "요새"),
    ("최근", "요새"),
    ("진짜", "참말로"),
    ("정말", "참말로"),
    ("빨리", "후딱"),
    ("얼른", "후딱"),
    ("천천히", "찬찬히"),
    ("진작", "진즉"),
    ("그런데", "헌데"),
    ("스마트폰", "핸드폰"),
    ("걱정", "근심"),
    ("고민", "근심"),
]


def _load_old_timer_replacements() -> list[tuple[str, str]]:
    """코퍼스에서 추출된 치환 규칙을 읽는다. 없으면 안전 기본값을 쓴다."""
    if LEXICON_PATH.exists():
        try:
            data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
            pairs = data.get("old_timer_replacements", [])
            loaded = [(old, new) for old, new in pairs if old and new]
            if loaded:
                return loaded
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return list(FALLBACK_OLD_TIMER_REPLACEMENTS)


OLD_TIMER_REPLACEMENTS = _load_old_timer_replacements()

# 강도별 파라미터
INTENSITY = {
    1: {"joke_per_sentence": 0.0, "min_jokes": 0, "max_jokes": 1,
        "hanja_prob": 0.15, "max_hanja": 1, "awkward_period": 0.1,
        "space_before_period": 0.05, "irregular_space": 0.03, "max_space_drops": 1,
        "period_break_prob": 0.0, "max_period_breaks": 0, "eye_smile_prob": 0.0, "max_eye_smiles": 0,
        "double_space_prob": 0.08,
        "phonetic_prob": 0.0, "max_phonetic": 0, "drop_exclaim": 0.5},
    2: {"joke_per_sentence": 0.15, "min_jokes": 0, "max_jokes": 1,
        "hanja_prob": 0.30, "max_hanja": 1, "awkward_period": 0.2,
        "space_before_period": 0.1, "irregular_space": 0.08, "max_space_drops": 1,
        "period_break_prob": 0.03, "max_period_breaks": 1, "eye_smile_prob": 0.04, "max_eye_smiles": 1,
        "double_space_prob": 0.10,
        "phonetic_prob": 0.05, "max_phonetic": 1, "drop_exclaim": 0.6},
    3: {"joke_per_sentence": 0.08, "min_jokes": 0, "max_jokes": 1,
        "hanja_prob": 0.45, "max_hanja": 2, "awkward_period": 0.35,
        "space_before_period": 0.2, "irregular_space": 0.14, "max_space_drops": 1,
        "period_break_prob": 0.08, "max_period_breaks": 1, "eye_smile_prob": 0.12, "max_eye_smiles": 1,
        "double_space_prob": 0.14,
        "phonetic_prob": 0.08, "max_phonetic": 1, "drop_exclaim": 0.7},
    4: {"joke_per_sentence": 0.16, "min_jokes": 0, "max_jokes": 1,
        "hanja_prob": 0.55, "max_hanja": 2, "awkward_period": 0.5,
        "space_before_period": 0.38, "irregular_space": 0.46, "max_space_drops": 3,
        "period_break_prob": 0.18, "max_period_breaks": 2, "eye_smile_prob": 0.28, "max_eye_smiles": 1,
        "double_space_prob": 0.22,
        "phonetic_prob": 0.30, "max_phonetic": 2, "drop_exclaim": 0.85},
    5: {"joke_per_sentence": 0.24, "min_jokes": 0, "max_jokes": 1,
        "hanja_prob": 0.6, "max_hanja": 3, "awkward_period": 0.9,
        "space_before_period": 0.78, "irregular_space": 0.96, "max_space_drops": 8,
        "period_break_prob": 0.58, "max_period_breaks": 4, "eye_smile_prob": 0.50, "max_eye_smiles": 2,
        "double_space_prob": 0.44,
        "phonetic_prob": 0.88, "max_phonetic": 5, "drop_exclaim": 1.0},
}


class AjaeStyler:
    def __init__(self, dad_jokes: list[str] | None = None):
        self.dad_jokes = dad_jokes if dad_jokes is not None else _load_dad_jokes()

    def apply(
        self,
        text: str,
        intensity: int = 3,
        rng: random.Random | None = None,
        context: str | None = None,
        joke_context: str | None = None,
    ) -> str:
        text = (text or "").strip()
        if not text:
            return text
        intensity = _clamp(intensity)
        params = INTENSITY[intensity]
        rng = rng or random.Random(_seed(text, intensity))
        if joke_context is None:
            joke_context = f"{context or ''} {text}"
        joke_context = joke_context.strip()
        text = _normalize_ajeossi_voice(text)
        if intensity >= 5:
            text = _apply_old_timer_words(text)
            text = _force_ajeossi_opening(text, rng)

        sentences = _merge_short_fragments([s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()])
        if not sentences:
            sentences = [text]

        hanja_budget = params["max_hanja"]
        phonetic_budget = params.get("max_phonetic", 0)
        eye_smile_budget = params.get("max_eye_smiles", 0)
        phonetic_used = 0
        eye_smile_used = 0
        styled: list[str] = []
        for idx, sentence in enumerate(sentences):
            sentence, used_phonetic = self._phonetic_typos(sentence, params, phonetic_budget, rng)
            phonetic_budget -= used_phonetic
            phonetic_used += used_phonetic
            sentence, used = self._annotate_hanja(sentence, params, hanja_budget, rng)
            hanja_budget -= used
            sentence = self._style_punctuation(sentence, params, rng)
            sentence, used_eye_smile = self._add_eye_smile(sentence, params, eye_smile_budget, rng)
            eye_smile_budget -= used_eye_smile
            eye_smile_used += used_eye_smile
            sentence = self._irregular_spacing(sentence, params, rng, idx, len(sentences))
            styled.append(sentence)

        if intensity >= 5 and phonetic_used == 0:
            styled = _force_one_phonetic(styled, rng)
        if intensity >= 5 and eye_smile_used == 0:
            styled = _force_one_eye_smile(styled, rng)
        if intensity >= 5:
            styled = _force_one_late_period_break(styled, rng)

        return self._weave_jokes(styled, params, rng, joke_context or text)

    # --- 한자 병기 ---
    def _annotate_hanja(self, sentence, params, budget, rng):
        if budget <= 0:
            return sentence, 0
        used = 0
        for word, hanja in HANJA_DICT.items():
            if used >= budget:
                break
            # 이미 병기된 경우 건너뜀
            if f"{word}(" in sentence:
                continue
            if word in sentence and rng.random() < params["hanja_prob"]:
                sentence = sentence.replace(word, f"{word}({hanja})", 1)
                used += 1
        return sentence, used

    # --- 마침표/느낌표 손질 ---
    def _style_punctuation(self, sentence, params, rng):
        sentence = sentence.strip()
        short = len(sentence) < 6  # 짧은 조각은 손대지 않는다(쪼개짐 방지)
        # 느낌표는 아저씨답게 마침표로 (강도에 따라)
        if "!" in sentence and rng.random() < params["drop_exclaim"]:
            sentence = sentence.replace("!", ".")
        if short:
            return sentence
        # 문장 끝에 마침표가 없으면 가끔 어색하게 붙임
        if not re.search(r"[.?!~]$", sentence) and rng.random() < params["awkward_period"]:
            sentence += "."
        # 마침표 앞에 공백을 두는 어색한 버릇
        if sentence.endswith(".") and rng.random() < params["space_before_period"]:
            sentence = sentence[:-1].rstrip() + " ."
        return sentence

    # --- 불규칙 띄어쓰기 ---
    def _irregular_spacing(self, sentence, params, rng, sentence_index=0, total_sentences=1):
        if rng.random() >= params["irregular_space"]:
            return sentence
        sentence = self._period_break_spacing(sentence, params, rng, sentence_index, total_sentences)
        # 영문/숫자/고유명사(ThinQ, VOC, 46만 등)는 붙이지 않는다. 한글-한글 사이만 손본다.
        space_positions = [m.start() for m in re.finditer(r"(?<=[가-힣]) (?=[가-힣])", sentence)]
        if not space_positions:
            return sentence
        drop_count = min(len(space_positions), rng.randint(1, params.get("max_space_drops", 1)))
        for pos in sorted(rng.sample(space_positions, drop_count), reverse=True):
            if rng.random() < params.get("double_space_prob", 0):
                sentence = sentence[:pos] + "  " + sentence[pos + 1:]
            else:
                sentence = sentence[:pos] + sentence[pos + 1:]
        return sentence

    def _period_break_spacing(self, sentence, params, rng, sentence_index=0, total_sentences=1):
        prob = params.get("period_break_prob", 0)
        if sentence_index == 0 and total_sentences > 1:
            return sentence
        elif sentence_index >= 1:
            prob = min(0.95, prob * 1.25)

        if rng.random() >= prob:
            return sentence
        positions = _korean_break_positions(sentence)
        if not positions:
            return sentence
        count = min(len(positions), max(1, min(3, params.get("max_period_breaks", 1))))
        pos = _weighted_period_position(positions, sentence_index, total_sentences, rng)
        chosen = {pos}
        if count > 1:
            remaining = [candidate for candidate in positions if abs(candidate - pos) > 6]
            if remaining:
                chosen.add(rng.choice(remaining))
        for pos in sorted(chosen, reverse=True):
            sentence = sentence[:pos] + ". " + sentence[pos + 1:]
        return sentence

    def _add_eye_smile(self, sentence, params, budget, rng):
        if budget <= 0 or "ㅡㅡ" in sentence:
            return sentence, 0
        if rng.random() >= params.get("eye_smile_prob", 0):
            return sentence, 0
        return _append_eye_smile(sentence), 1

    # --- 발음식 맞춤법 흔들기 ---
    def _phonetic_typos(self, sentence, params, budget, rng):
        if budget <= 0:
            return sentence, 0
        if rng.random() >= params.get("phonetic_prob", 0):
            return sentence, 0
        candidates = [(old, new) for old, new in PHONETIC_REPLACEMENTS if old in sentence]
        if not candidates:
            return sentence, 0
        rng.shuffle(candidates)
        used = 0
        for old, new in candidates:
            if used >= budget:
                break
            sentence = sentence.replace(old, new, 1)
            used += 1
        return sentence, used

    # --- 아재개그 삽입 ---
    def _weave_jokes(self, sentences, params, rng, context):
        explicit = _explicit_joke_request(context)
        contextual = _matched_contextual_jokes(context)
        out: list[str] = [sentence.strip() for sentence in sentences if sentence.strip()]
        if not out:
            return _join_sentences(sentences)

        if explicit:
            # 사용자가 개그를 직접 요청: 주제가 맞는 유명개그가 있으면 그걸,
            # 없으면 검증된 대형 풀(781개)에서 아무거나 하나 꺼낸다.
            pool = contextual or self.dad_jokes
            if not pool:
                return _join_sentences(sentences)
            joke = rng.choice(pool)
            target_idx = _best_joke_target(out, context) if contextual else len(out) - 1
            reaction = True
        else:
            # 대화 중 자연 삽입: 주제 키워드가 맞는 유명개그만, 확률 게이트.
            if not contextual:
                return _join_sentences(sentences)
            if not _has_exact_famous_joke_context(context) and rng.random() >= params["joke_per_sentence"]:
                return _join_sentences(sentences)
            joke = rng.choice(contextual)
            target_idx = _best_joke_target(out, context)
            reaction = rng.random() < 0.5  # 자연 삽입은 가끔만 반응을 덧붙인다

        out[target_idx] = _append_contextual_joke(out[target_idx], joke)
        if reaction:
            out[target_idx] = _append_joke_reaction(out[target_idx], rng)
        return " ".join(part.strip() for part in out if part.strip())


def _merge_short_fragments(sentences: list[str], min_len: int = 6) -> list[str]:
    """문장 분리 후 생긴 짧은 조각(예: '건강', '내가 해')을 앞 문장에 붙여,
    농담이 문장 중간을 끊고 들어가 어색해지는 것을 막는다."""
    merged: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if merged and len(sentence) < min_len:
            merged[-1] = f"{merged[-1]} {sentence}".strip()
        elif merged and len(merged[-1]) < min_len:
            merged[-1] = f"{merged[-1]} {sentence}".strip()
        else:
            merged.append(sentence)
    return merged


def _join_sentences(sentences: list[str]) -> str:
    return " ".join(sentence.strip() for sentence in sentences if sentence.strip())


def _apply_old_timer_words(text: str) -> str:
    for old, new in OLD_TIMER_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _force_one_phonetic(sentences: list[str], rng: random.Random) -> list[str]:
    candidates: list[tuple[int, str, str]] = []
    for idx, sentence in enumerate(sentences):
        for old, new in PHONETIC_REPLACEMENTS:
            if old in sentence:
                candidates.append((idx, old, new))
    if not candidates:
        return sentences

    idx, old, new = rng.choice(candidates)
    changed = sentences[:]
    changed[idx] = changed[idx].replace(old, new, 1)
    return changed


def _force_one_eye_smile(sentences: list[str], rng: random.Random) -> list[str]:
    candidates = [idx for idx, sentence in enumerate(sentences) if len(sentence) >= 10 and "ㅡㅡ" not in sentence]
    if not candidates:
        return sentences
    idx = rng.choice(candidates)
    changed = sentences[:]
    changed[idx] = _append_eye_smile(changed[idx])
    return changed


def _force_one_late_period_break(sentences: list[str], rng: random.Random) -> list[str]:
    if any(re.search(r"[가-힣]\. [가-힣]", sentence) for sentence in sentences):
        return sentences

    candidates: list[tuple[int, list[int]]] = []
    for idx, sentence in enumerate(sentences):
        if idx == 0:
            continue
        positions = _korean_break_positions(sentence)
        if positions:
            candidates.append((idx, positions))
    if not candidates:
        return sentences

    idx, positions = rng.choice(candidates)
    changed = sentences[:]
    pos = _weighted_period_position(positions, idx, len(sentences), rng)
    changed[idx] = changed[idx][:pos] + ". " + changed[idx][pos + 1:]
    return changed


def _append_eye_smile(sentence: str) -> str:
    sentence = sentence.rstrip()
    if not sentence:
        return sentence
    if sentence.endswith("."):
        return sentence[:-1].rstrip() + " ㅡㅡ."
    if sentence.endswith(("?", "!", "~")):
        return sentence + " ㅡㅡ"
    return sentence + " ㅡㅡ"


# 수량 표현이 마침표로 쪼개지면 뜻이 깨진다(세 개 -> 세. 개). 그 앞 음절을 보호한다.
_NUMERAL_BEFORE = set("한두세네댓몇여러스무")


def _korean_break_positions(sentence: str) -> list[int]:
    """한글-한글 사이의 띄어쓰기 위치. 단, 수량 표현(세 개, 두 명...)은 안 쪼갠다."""
    return [
        m.start()
        for m in re.finditer(r"(?<=[가-힣]) (?=[가-힣])", sentence)
        if sentence[m.start() - 1] not in _NUMERAL_BEFORE
    ]


def _weighted_period_position(positions: list[int], sentence_index: int, total_sentences: int, rng: random.Random) -> int:
    if not positions:
        return 0
    if total_sentences <= 1:
        low, high = 0.35, 0.82
    else:
        ratio = sentence_index / max(1, total_sentences - 1)
        if ratio < 0.34:
            low, high = 0.42, 0.78
        elif ratio < 0.67:
            low, high = 0.22, 0.72
        else:
            low, high = 0.16, 0.62

    last = max(positions)
    preferred = [pos for pos in positions if low <= (pos / max(1, last)) <= high]
    return rng.choice(preferred or positions)


def _matched_contextual_jokes(context: str) -> list[str]:
    """문맥 키워드가 맞는 유명개그만 고른다.
    개그를 직접 요청하면 문턱을 1로 낮춰 살짝만 맞아도 그 주제 개그를 쓰고,
    아무 주제도 안 잡히면 빈 리스트(-> 대형 풀에서 아무거나)로 둔다."""
    compact = (context or "").replace(" ", "")
    explicit_request = _explicit_joke_request(context)
    jokes: list[str] = []
    for item in FAMOUS_CONTEXTUAL_DAD_JOKES:
        matches = sum(1 for keyword in item["keywords"] if keyword in compact)
        threshold = 1 if explicit_request else item.get("min_matches", 2)
        if matches >= threshold:
            jokes.append(item["text"])
    return jokes


def _explicit_joke_request(context: str) -> bool:
    compact = (context or "").replace(" ", "")
    return any(keyword in compact for keyword in JOKE_REQUEST_KEYWORDS)


def _has_exact_famous_joke_context(context: str) -> bool:
    compact = (context or "").replace(" ", "")
    return any(
        sum(1 for keyword in item["keywords"] if keyword in compact) >= item.get("min_matches", 2)
        for item in FAMOUS_CONTEXTUAL_DAD_JOKES
    )


def _best_joke_target(sentences: list[str], context: str) -> int:
    compact_context = (context or "").replace(" ", "")
    for item in FAMOUS_CONTEXTUAL_DAD_JOKES:
        if sum(1 for keyword in item["keywords"] if keyword in compact_context) < item.get("min_matches", 2):
            continue
        for idx, sentence in enumerate(sentences):
            compact_sentence = sentence.replace(" ", "")
            if any(keyword in compact_sentence for keyword in item["keywords"]):
                return idx
    return max(0, len(sentences) - 1)


def _append_contextual_joke(sentence: str, joke: str) -> str:
    sentence = sentence.rstrip()
    if not sentence:
        return joke
    if sentence.endswith((".", "?", "!", "~")):
        return f"{sentence} {joke}"
    return f"{sentence}. {joke}"


# 개그를 친 뒤 박춘배가 보이는 반응. 세 갈래로 나눠 무작위로 하나를 붙인다.
# (1) 스스로 웃음: 으하하/흐하하/ㅎ 류 (크크 같은 건 안 쓴다)
# (2) 반응 요구: 웃음 + '정말 웃기지?' + 더 큰 웃음
# (3) 안 웃으면 핀잔: 바로 하지 말고 점/띄어쓰기로 뜸 들인 뒤에 한다.
JOKE_REACTIONS = {
    "self_laugh": [
        "으하하.",
        "흐하하.",
        "ㅎ.",
        "으하하하.",
        "흐흐.",
        "허허.",
    ],
    "demand": [
        "흐하하. 정말 웃기지? 흐하하하.",
        "으하하. 이거 정말 웃기지 않냐. 으하하하.",
        "흐흐. 정말 웃기지? 흐하하.",
        "으하하. 방금 거 명작이지. 으하하하.",
    ],
    "scold": [
        "왜 안 웃냐.",
        "표정이 왜 그래. 이런 건 좀 웃어줘야 정이 붙는 거다.",
        "반응이 영 시원찮네.",
        "어허 이런 게 다 인생 공부여.",
    ],
}
_JOKE_REACTION_KINDS = list(JOKE_REACTIONS)
# 핀잔 전에 '반응을 기다리는' 뜸. 점이나 공백으로 한 박자 띄운다.
_SCOLD_PAUSES = [" ......  ", " ...  ...  ", "  ....  ", "      ", " ...... "]


def _append_joke_reaction(sentence: str, rng: random.Random) -> str:
    kind = rng.choice(_JOKE_REACTION_KINDS)
    reaction = rng.choice(JOKE_REACTIONS[kind])
    sentence = sentence.rstrip()
    if sentence and not sentence.endswith((".", "?", "!", "~")):
        sentence += "."
    if kind == "scold":
        # 바로 핀잔하지 않고, 점/띄어쓰기로 뜸을 들인 뒤에 한다.
        return f"{sentence}{rng.choice(_SCOLD_PAUSES)}{reaction}".rstrip()
    return f"{sentence} {reaction}".strip()


# LLM 이 젊은층 줄임말이나 어색한 외래어/없는 말을 내보내도 윗세대 말로 되돌리는 안전장치.
# 60대 아저씨는 '포트폴리오' 대신 '작업물/이력'이라 하고, '면접자리' 같은 없는 말은 안 쓴다.
YOUTH_SLANG_GUARD = [
    ("걍", "그냥"),
    ("포트폴리오", "작업물"),
    ("포폴", "작업물"),
    ("면접자리", "면접"),
    ("아아", "아이스 아메리카노"),
    ("취준", "취업 준비"),
    ("자만추", "자연스럽게 만나기"),
    ("ㄹㅇ", "진짜"),
    ("ㅇㅈ", "인정"),
    ("노잼", "재미없"),
    ("꿀잼", "재미있"),
    ("존나", "되게"),
    ("ㅈㄴ", "되게"),
    ("킹받", "열받"),
]


def _scrub_youth_slang(text: str) -> str:
    for slang, proper in YOUTH_SLANG_GUARD:
        text = text.replace(slang, proper)
    return text


def scrub_youth_slang(text: str) -> str:
    """공개 진입점. LLM 스트리밍 중간 텍스트에서도 젊은말을 즉시 되돌리는 데 쓴다."""
    return _scrub_youth_slang(text)


def _normalize_ajeossi_voice(text: str) -> str:
    text = EMOJI_RE.sub("", text)
    text = _scrub_youth_slang(text)
    text = _enforce_banmal(text)
    replacements = [
        ("아이고, 배고픔이 심하시구나.", "어이구. 배 많이 고프구만."),
        ("아이고 배고픔이 심하시구나.", "어이구. 배 많이 고프구만."),
        ("배고픔이 심하시구나", "배 많이 고프구만"),
        ("아침은 꼭 챙겨 먹는 게 건강에 좋아요.", "아침은 꼭 챙겨 먹어라. 몸 버티는 기본이다."),
        ("아침은 꼭 챙겨 먹는 게 건강에 좋아요", "아침은 꼭 챙겨 먹어라. 몸 버티는 기본이다"),
        ("간단하게라도 과일이나 견과류로 시작해보시는 건 어떨까요?", "과일이니 견과류니 너무 따지지 말고, 있는 밥부터 한술 떠라."),
        ("간단하게라도 과일이나 견과류로 시작해보시는 건 어떨까요", "과일이니 견과류니 너무 따지지 말고, 있는 밥부터 한술 떠라"),
        ("건강도 지키고 하루를 활기차게 시작할 수 있을 거예요.", "그래야 하루가 좀 버틴다. 밥심이 괜히 있는 말이 아니다."),
        ("건강도 지키고 하루를 활기차게 시작할 수 있을 거예요", "그래야 하루가 좀 버틴다. 밥심이 괜히 있는 말이 아니다"),
        ("시작해보시는 건 어떨까요", "시작해봐라"),
        ("해보시는 건 어떨까요", "해봐라"),
        ("챙겨 먹는  게", "챙겨 먹는 게"),
        ("챙겨 먹는 게", "챙겨 먹는 게"),
        ("제가 ", "내가 "),
        ("저는 ", "나는 "),
        ("좋아요", "좋다"),
        ("좋습니다", "좋다"),
        ("어떨까요", "어떠냐"),
        ("거예요", "거다"),
        ("거에요", "거다"),
        ("더라고요", "더라"),
        ("하세요", "해라"),
        ("해보세요", "해봐라"),
        ("드세요", "먹어라"),
        ("드시고", "먹고"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    text = _enforce_banmal(text)
    text = re.sub(
        r"아침은 꼭 챙겨 먹는\s+게 건강에 좋다[.]?",
        "아침은 꼭 챙겨 먹어라. 몸 버티는 기본이다.",
        text,
    )
    text = re.sub(r"\s+\.", " .", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _enforce_banmal(text: str) -> str:
    replacements = [
        ("하겠습니다", "하겠다"),
        ("했습니다", "했다"),
        ("되었습니다", "됐다"),
        ("있었습니다", "있었다"),
        ("없었습니다", "없었다"),
        ("맡았습니다", "맡았다"),
        ("만들었습니다", "만들었다"),
        ("연결했습니다", "연결했다"),
        ("분석했습니다", "분석했다"),
        ("정리했습니다", "정리했다"),
        ("가깝습니다", "가깝다"),
        ("어울립니다", "어울린다"),
        ("움직입니다", "움직인다"),
        ("느껴집니다", "느껴진다"),
        ("이어집니다", "이어진다"),
        ("보여줍니다", "보여준다"),
        ("보입니다", "보인다"),
        ("알려줍니다", "알려준다"),
        ("안내합니다", "알려준다"),
        ("바꿉니다", "바꾼다"),
        ("만듭니다", "만든다"),
        ("줍니다", "준다"),
        ("봅니다", "본다"),
        ("갑니다", "간다"),
        ("옵니다", "온다"),
        ("아닙니다", "아니다"),
        ("합니다", "한다"),
        ("됩니다", "된다"),
        ("있습니다", "있다"),
        ("없습니다", "없다"),
        ("입니다", "이다"),
        ("습니다", "다"),
        ("합니다", "한다"),
        ("했습니다", "했다"),
        ("드릴게요", "줄게"),
        ("할게요", "할게"),
        ("볼게요", "볼게"),
        ("주세요", "줘라"),
        ("해요", "해라"),
        ("돼요", "된다"),
        ("되요", "된다"),
        ("이에요", "이다"),
        ("예요", "이다"),
        ("거예요", "거다"),
        ("거에요", "거다"),
        ("네요", "네"),
        ("군요", "구만"),
        ("까요", "까"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(r"([가-힣])요([.?!~]?)(?=\s|$)", _demote_polite_yo, text)
    return text


def _demote_polite_yo(match: re.Match) -> str:
    """문장 끝 '~요'를 반말로 바꾼다.

    '했어요/없어요/추워요/봐요'처럼 받침 없는 열린 음절 뒤의 요는 그냥 떼면
    자연스러운 반말이 된다(했어, 없어, 추워, 봐). 무조건 '~다'로 박으면
    '했어다, 추워다'처럼 외계어가 되므로, 받침 유무로 나눠 처리한다.
    """
    syllable, tail = match.group(1), match.group(2)
    code = ord(syllable)
    has_batchim = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0
    return f"{syllable}다{tail}" if has_batchim else f"{syllable}{tail}"


def _force_ajeossi_opening(text: str, rng: random.Random) -> str:
    if not text:
        return text
    starts = (
        "어이구", "아이고", "어허", "그거", "그건", "내가", "나는", "밥", "일단",
        "자", "음", "들어봐라", "박춘배",
    )
    if text.startswith(starts):
        return text
    openers = ["어이구.", "그거 말이다.", "내가 볼 땐 말이야.", "일단 말이지."]
    return f"{rng.choice(openers)} {text}"


def _load_dad_jokes() -> list[str]:
    if not DAD_JOKES_PATH.exists():
        return DEFAULT_DAD_JOKES[:]
    try:
        data = json.loads(DAD_JOKES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DEFAULT_DAD_JOKES[:]
    if isinstance(data, dict):
        jokes = [str(j) for j in data.get("jokes", [])]
    else:
        jokes = [str(j) for j in data]
    return jokes or DEFAULT_DAD_JOKES[:]


def _clamp(intensity: int) -> int:
    try:
        intensity = int(intensity)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, intensity))


def _seed(text: str, intensity: int) -> int:
    digest = hashlib.md5(f"{intensity}:{text}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)
