"""Rule-based safety filter.

두 군데에서 쓰인다.
1) 수집/정제 단계: 원문에서 위협/집단비하/과도 욕설을 표지하고 가린다.
2) 챗봇 출력 단계: 모델이 만든 답에서 혐오/비하/개인정보/욕설을 마지막으로 한 번 더 거른다.

clean_text.py 가 이 모듈을 import 하므로, 순환 import 를 피하기 위해
이 파일은 프로젝트 내부 모듈을 import 하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SafetyResult:
    text: str
    flags: list[str] = field(default_factory=list)


class SafetyFilter:
    # --- 콘텐츠 안전 ---
    THREAT_RE = re.compile(r"(죽여|죽이|패버|때려죽|테러|폭파|살해|불 ?질러)", re.IGNORECASE)
    TARGETED_HATE_RE = re.compile(
        r"([가-힣A-Za-z0-9_]{1,20})(들|은|는|이|가)?\s*"
        r"(열등|멸종|박멸|추방|쓰레기|벌레|없애야|죽어야|꺼져야)",
        re.IGNORECASE,
    )
    EXCESSIVE_PROFANITY_RE = re.compile(r"(씨발|시발|개새끼|병신|좆|꺼져|닥쳐)", re.IGNORECASE)

    # --- 개인정보 (출력 방어용) ---
    EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    PHONE_RE = re.compile(
        r"(?<!\d)(?:\+?82[-.\s]?)?0?1[016789][-\s.]?\d{3,4}[-.\s]?\d{4}(?!\d)|"
        r"(?<!\d)0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)"
    )
    ACCOUNT_RE = re.compile(r"(?<!\d)\d{2,6}[-\s]\d{2,6}[-\s]\d{2,8}(?!\d)")
    RRN_RE = re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")
    CARD_RE = re.compile(r"(?<!\d)\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}(?!\d)")

    def scan(self, text: str) -> list[str]:
        flags: list[str] = []
        if self.THREAT_RE.search(text):
            flags.append("threat")
        if self.TARGETED_HATE_RE.search(text):
            flags.append("targeted_hate")
        if len(self.EXCESSIVE_PROFANITY_RE.findall(text)) >= 2:
            flags.append("excessive_profanity")
        if self._has_pii(text):
            flags.append("pii")
        return flags

    def sanitize(self, text: str) -> SafetyResult:
        flags = self.scan(text)
        sanitized = text
        sanitized = self.THREAT_RE.sub("[위협]", sanitized)
        sanitized = self.TARGETED_HATE_RE.sub("[비하]", sanitized)
        if "excessive_profanity" in flags:
            sanitized = self.EXCESSIVE_PROFANITY_RE.sub("[욕설]", sanitized)
        sanitized = self._mask_pii(sanitized)
        return SafetyResult(text=sanitized, flags=flags)

    def is_blocked_user_request(self, text: str) -> bool:
        """사람/집단을 해치거나 깎아내려 달라는 요청은 통째로 거절한다."""
        flags = self.scan(text)
        return "threat" in flags or "targeted_hate" in flags

    def _has_pii(self, text: str) -> bool:
        return any(
            pattern.search(text)
            for pattern in (self.EMAIL_RE, self.PHONE_RE, self.ACCOUNT_RE, self.RRN_RE, self.CARD_RE)
        )

    def _mask_pii(self, text: str) -> str:
        text = self.EMAIL_RE.sub("[이메일 생략]", text)
        text = self.RRN_RE.sub("[주민번호 생략]", text)
        text = self.CARD_RE.sub("[카드번호 생략]", text)
        text = self.ACCOUNT_RE.sub("[계좌 생략]", text)
        text = self.PHONE_RE.sub("[연락처 생략]", text)
        return text
