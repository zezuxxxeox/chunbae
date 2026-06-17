"""수집한 코퍼스에서 '말투 패턴'만 추출해 persona/lexicon.json 으로 굳히는 단계.

설계 원칙(요구사항 그대로):
  수집(data/seed, data/raw)
    -> 패턴화 (어휘 빈도 / 종결어미 / 문장부호·띄어쓰기 지표 추출)
    -> 원본 삭제 (--purge-raw 로 원문 jsonl 제거; 저작권·개인정보·보관 리스크 제거)
    -> 패턴만 남김 (persona/lexicon.json) -> style_engine 이 이것만 보고 말투를 입힘

핵심: persona 가 쓰는 옛말투 단어는 '내가 임의로 적은 것'이 아니라
'코퍼스에 실제로 나온(attested) 단어만' 채택한다. 코퍼스에 없으면 버린다.
그래서 '걍/포폴/인터네트' 같은 건 애초에 후보에 없고, 후보라도 코퍼스에
안 나오면 자동 탈락한다.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from style_features import extract_style_features


WORD_RE = re.compile(r"[가-힣]+")
# 문장 끝 종결 꼬리(마지막 어절의 끝 2~4글자)를 본다.
SENT_SPLIT_RE = re.compile(r"[.!?\n]+")

# 현대/젊은말 -> 윗세대 동의어 후보. 여기서 '오른쪽(윗세대 단어)'이
# 코퍼스에 실제로 나올 때만 치환 규칙으로 채택한다(데이터 기반 필터).
# 뜻이 바뀌는 치환은 후보에 넣지 않는다.
# 맥락을 가려야 자연스러운 치환도 뺀다. 예: '준비->채비'는 '나갈 채비'엔 맞아도
# '면접 준비/취업 준비'엔 어색하다. 그래서 '준비'는 그냥 둔다(윗세대도 '준비'를 쓴다).
CANDIDATE_REPLACEMENTS: list[tuple[str, str]] = [
    ("요즘", "요새"),
    ("최근", "요새"),
    ("빨리", "후딱"),
    ("얼른", "후딱"),
    ("천천히", "찬찬히"),
    ("진작", "진즉"),
    ("그런데", "헌데"),
    ("스마트폰", "핸드폰"),
    ("걱정", "근심"),
    ("고민", "근심"),
    ("진짜", "참말로"),
    ("정말", "참말로"),
    ("전혀", "통"),
    ("링크", "주소"),
]

# 세대 식별용: 윗세대 코퍼스에 '있으면 안 되는' 젊은층 줄임말/신조어.
# 리포트에서 코퍼스에 정말 없는지 확인용으로만 쓴다.
YOUTH_SLANG_BLOCKLIST = ["걍", "포폴", "ㅇㅇ", "ㄱㄱ", "인정", "오짐", "킹받", "갓생", "버카충"]

# 실데이터(공개 게시판)엔 욕설이 섞인다. 패턴 리포트/어휘 통계에서만 가린다
# (실제 persona 규칙은 CANDIDATE_REPLACEMENTS 만 쓰므로 어차피 안 들어간다).
PROFANITY = ["씨발", "씨부", "시발", "개새", "병신", "좆", "존나", "ㅈ같", "ㅅㅂ", "ㅄ", "느금", "애미"]


def _is_clean(token: str) -> bool:
    return not any(bad in token for bad in PROFANITY)


def iter_corpus(paths: list[Path]) -> list[dict]:
    records: list[dict] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def _word_counter(texts: list[str]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(WORD_RE.findall(text))
    return counter


def _ending_counter(texts: list[str], min_len: int = 2, max_len: int = 4) -> Counter[str]:
    """문장 끝 어절의 꼬리(2~4글자)를 세서 실제 종결 습관을 본다."""
    endings: Counter[str] = Counter()
    for text in texts:
        for sentence in SENT_SPLIT_RE.split(text):
            words = WORD_RE.findall(sentence)
            if not words:
                continue
            tail = words[-1]
            for n in range(min_len, max_len + 1):
                if len(tail) >= n:
                    endings[tail[-n:]] += 1
    return endings


def build_lexicon(records: list[dict], top_vocab: int = 60) -> dict:
    texts = [str(r.get("text", "")) for r in records if str(r.get("text", "")).strip()]
    word_counts = Counter({w: c for w, c in _word_counter(texts).items() if _is_clean(w)})
    ending_counts = Counter({e: c for e, c in _ending_counter(texts).items() if _is_clean(e)})
    style = extract_style_features(records)

    attested: dict[str, int] = {}
    dropped: list[str] = []
    replacements: list[list[str]] = []
    for modern, older in CANDIDATE_REPLACEMENTS:
        hits = sum(text.count(older) for text in texts)
        if hits > 0:
            attested[older] = hits
            replacements.append([modern, older])
        else:
            dropped.append(f"{modern}->{older}")

    slang_found = {w: sum(t.count(w) for t in texts) for w in YOUTH_SLANG_BLOCKLIST}
    slang_found = {w: c for w, c in slang_found.items() if c > 0}

    return {
        "profile": "ajeossi_lexicon_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(texts),
        "raw_source_purged": False,
        "patterns": {
            "period_per_100_chars": style.period_per_100_chars,
            "multi_space_count": style.multi_space_count,
            "space_before_punct_count": style.space_before_punctuation_count,
            "hanja_pair_count": style.hanja_pair_count,
            "recall_expr_count": style.recall_expression_count,
            "experience_expr_count": style.experience_expression_count,
        },
        "top_vocabulary": dict(word_counts.most_common(top_vocab)),
        "top_endings": dict(ending_counts.most_common(30)),
        # style_engine 이 실제로 읽어 쓰는 부분: 코퍼스에서 검증된 치환 규칙만.
        "old_timer_replacements": replacements,
        "attested_old_words": attested,
        "dropped_unattested": dropped,
        "youth_slang_in_corpus": slang_found,
    }


def write_report(lexicon: dict, path: Path) -> None:
    p = lexicon["patterns"]
    lines = [
        "# 박춘배 말투 패턴 리포트 (코퍼스 추출 결과)",
        "",
        f"- 생성: {lexicon['generated_at']}",
        f"- 문서 수: {lexicon['document_count']}",
        f"- 100자당 마침표: {p['period_per_100_chars']}",
        f"- 다중 공백 사례: {p['multi_space_count']}",
        f"- 문장부호 앞 공백: {p['space_before_punct_count']}",
        f"- 한자 병기: {p['hanja_pair_count']}",
        f"- 회상/경험 표현: 회상 {p['recall_expr_count']} / 경험 {p['experience_expr_count']}",
        "",
        "## 채택된 옛말투 치환 (코퍼스에서 검증됨)",
        "",
    ]
    for modern, older in lexicon["old_timer_replacements"]:
        hits = lexicon["attested_old_words"].get(older, 0)
        lines.append(f"- `{modern}` -> `{older}`  (코퍼스 출현 {hits}회)")
    if lexicon["dropped_unattested"]:
        lines += ["", "## 코퍼스에 없어 탈락한 후보", ""]
        lines += [f"- {d}" for d in lexicon["dropped_unattested"]]
    lines += ["", "## 자주 쓰인 종결 꼬리 (상위 15)", ""]
    for ending, count in list(lexicon["top_endings"].items())[:15]:
        lines.append(f"- `…{ending}`: {count}")
    lines += ["", "## 자주 쓰인 단어 (상위 25)", ""]
    for word, count in list(lexicon["top_vocabulary"].items())[:25]:
        lines.append(f"- `{word}`: {count}")
    lines += ["", "## 젊은층 줄임말 점검", ""]
    if lexicon["youth_slang_in_corpus"]:
        lines.append(f"- 발견됨(점검 필요): {lexicon['youth_slang_in_corpus']}")
    else:
        lines.append("- 코퍼스에서 젊은층 줄임말 미발견 (세대 톤 일관성 OK)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def purge_raw(dirs: list[Path]) -> list[str]:
    """패턴 추출이 끝났으니 원문 jsonl 을 삭제한다(저작권·개인정보·보관 리스크 제거)."""
    removed: list[str] = []
    for d in dirs:
        if not d.exists():
            continue
        for f in d.glob("*.jsonl"):
            f.unlink()
            removed.append(str(f))
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="코퍼스에서 말투 패턴만 추출해 persona/lexicon.json 으로 굳힌다.")
    parser.add_argument("--seed-dir", default="data/seed")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--out", default="persona/lexicon.json")
    parser.add_argument("--report", default="analysis/ajeossi_style_report.md")
    parser.add_argument("--purge-raw", action="store_true",
                        help="추출 후 data/raw, data/seed 의 원문 jsonl 삭제 (패턴만 남김)")
    args = parser.parse_args()

    seed_dir, raw_dir = Path(args.seed_dir), Path(args.raw_dir)
    paths = sorted(seed_dir.glob("*.jsonl")) + sorted(raw_dir.glob("*.jsonl"))
    records = iter_corpus(paths)
    if not records:
        print("코퍼스가 비어 있다. data/seed 또는 data/raw 에 jsonl 을 먼저 넣어라.")
        return

    lexicon = build_lexicon(records)

    removed: list[str] = []
    if args.purge_raw:
        # 스크랩 원본(data/raw)만 지운다. 패턴은 이미 lexicon 으로 추출됐다.
        # 내가 직접 쓴 관찰 seed(data/seed)는 재현용으로 남긴다.
        removed = purge_raw([raw_dir])
        lexicon["raw_source_purged"] = True

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(lexicon, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(lexicon, Path(args.report))

    print(f"문서 {lexicon['document_count']}건에서 패턴 추출 -> {out}")
    print(f"채택된 치환 {len(lexicon['old_timer_replacements'])}개, 탈락 {len(lexicon['dropped_unattested'])}개")
    print(f"리포트 -> {args.report}")
    if removed:
        print(f"원문 {len(removed)}개 삭제(패턴만 보관): {removed}")


if __name__ == "__main__":
    main()
