"""공개 아재개그 모음에서 '검증된(실제 유통되는)' 개그만 모아 persona/dad_jokes.json 으로 굳힌다.

수집 -> 파싱 -> 중복제거 -> 안전필터 -> 저장. 원천 파일은 data/raw/jokes_src 에 둔다
(말투 코퍼스처럼 --purge 로 원본을 지우고 결과만 남길 수도 있다).
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SRC = Path("data/raw/jokes_src")

# 혐오/성/정치/차별 표현이 든 개그는 버린다(안전 기준).
BAD_WORDS = [
    "씨발", "개새", "병신", "장애인", "정신병", "틀딱", "한남", "김치녀", "전라디",
    "홍어", "운지", "일베", "섹스", "성기", "자지", "보지", "음경", "변태", "창녀",
    "후장", "애미", "느금", "좆", "엠창", "supp",
]


def _safe(text: str) -> bool:
    return not any(b in text for b in BAD_WORDS)


def _clean(text: str) -> str:
    # 강조용 따옴표 제거 + 군더더기 공백 정리.
    text = text.replace("“", "").replace("”", "").replace('"', "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _as_text(question: str, answer: str) -> str:
    question, answer = _clean(question), _clean(answer)
    if answer:
        text = f"{question} {answer}".strip()
    else:
        text = question
    if not re.search(r"[.!?~]$", text):
        text += "."
    return text


def parse_sources() -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []  # (question, answer, source)

    aje = SRC / "ajegag.json"
    if aje.exists():
        data = json.loads(aje.read_text(encoding="utf-8"))
        for p in data.get("problems", []):
            ans = p.get("answer")
            ans = ans[0] if isinstance(ans, list) and ans else (ans if isinstance(ans, str) else "")
            pairs.append((str(p.get("quiz", "")), str(ans), "Stop-uncle"))

    ts = SRC / "jokes.ts"
    if ts.exists():
        t = ts.read_text(encoding="utf-8")
        for m in re.finditer(r'question:\s*"([^"]*)"\s*,\s*answer:\s*"([^"]*)"', t):
            pairs.append((m.group(1), m.group(2), "ysoftman-dadjoke"))

    qp = SRC / "quiz.py"
    if qp.exists():
        t = qp.read_text(encoding="utf-8")
        for m in re.finditer(r'"q":\s*"([^"]*)"\s*,\s*"a":\s*"([^"]*)"', t):
            pairs.append((m.group(1), m.group(2), "ajaequiz"))

    gg = SRC / "gags.txt"
    if gg.exists():
        for line in gg.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                pairs.append((line, "", "mnyu-gags"))

    return pairs


def build(pairs: list[tuple[str, str, str]]) -> dict:
    seen: set[str] = set()
    jokes: list[str] = []
    by_src: dict[str, int] = {}
    for q, a, src in pairs:
        if not q.strip():
            continue
        text = _as_text(q, a)
        if not _safe(text):
            continue
        if not (4 <= len(text) <= 80):
            continue
        key = re.sub(r"\s+", "", q) + "|" + re.sub(r"\s+", "", a)
        if key in seen:
            continue
        seen.add(key)
        jokes.append(text)
        by_src[src] = by_src.get(src, 0) + 1

    return {
        "profile": "verified_dad_jokes_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(jokes),
        "sources": {
            "Stop-uncle": "github.com/Team-WAVE-x/Stop-uncle (src/ajegag.json)",
            "ysoftman-dadjoke": "github.com/ysoftman/dadjoke (src/jokes.ts)",
            "ajaequiz": "github.com/choijiye0n/ajaequiz (quiz.py)",
            "mnyu-gags": "github.com/mnyu123/gags (gags.txt)",
        },
        "source_counts": by_src,
        "note": "공개 GitHub 아재개그 모음에서 수집·중복제거·안전필터한 검증 풀.",
        "jokes": jokes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="검증된 아재개그 풀 생성")
    parser.add_argument("--out", default="persona/dad_jokes.json")
    parser.add_argument("--purge-src", action="store_true", help="생성 후 원천 파일(data/raw/jokes_src) 삭제")
    args = parser.parse_args()

    pairs = parse_sources()
    result = build(pairs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"원천 {len(pairs)}개 -> 검증 풀 {result['count']}개 저장: {out}")
    print(f"출처별: {result['source_counts']}")

    if args.purge_src and SRC.exists():
        for f in SRC.glob("*"):
            f.unlink()
        SRC.rmdir()
        print("원천 파일 삭제(결과만 보관)")


if __name__ == "__main__":
    main()
