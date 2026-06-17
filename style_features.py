from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Iterable


HANJA_RE = re.compile(r"[一-龥]+")
HANJA_PAIR_RE = re.compile(r"[가-힣A-Za-z]{1,20}\([一-龥]{1,12}\)")
MULTI_SPACE_RE = re.compile(r"[^\n]\s{2,}[^\n]")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+[,.!?]")
RECALL_RE = re.compile(r"(예전|그때|옛날|젊었을 때|나 때는|전에 말이죠|돌이켜보면)")
EXPERIENCE_RE = re.compile(r"(제가 보기엔|경험상|내가 해보니|살아보니|사람 사는 게|결국은)")
ENDING_PATTERNS = [
    "합니다.",
    "하시길 바랍니다.",
    "라는 얘기입니다.",
    "하는 게 맞습니다.",
    "인 겁니다.",
    "해야 합니다.",
    "보시면 됩니다.",
]


@dataclass
class StyleFeatureSummary:
    document_count: int = 0
    total_chars: int = 0
    avg_text_length: float = 0.0
    period_count: int = 0
    period_per_100_chars: float = 0.0
    question_count: int = 0
    exclamation_count: int = 0
    repeated_punctuation_count: int = 0
    multi_space_count: int = 0
    space_before_punctuation_count: int = 0
    hanja_pair_count: int = 0
    recall_expression_count: int = 0
    experience_expression_count: int = 0
    ending_counts: dict[str, int] = field(default_factory=dict)
    spacing_examples: list[str] = field(default_factory=list)
    hanja_examples: list[str] = field(default_factory=list)
    ending_examples: list[str] = field(default_factory=list)


def load_jsonl(path: str | Path) -> list[dict]:
    records: list[dict] = []
    with Path(path).open("r", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                records.append(json.loads(line))
    return records


def extract_style_features(records: Iterable[dict]) -> StyleFeatureSummary:
    texts = [str(record.get("text", "")) for record in records if str(record.get("text", "")).strip()]
    total_chars = sum(len(text) for text in texts)
    ending_counter: Counter[str] = Counter()
    spacing_examples: list[str] = []
    hanja_examples: list[str] = []
    ending_examples: list[str] = []

    summary = StyleFeatureSummary(
        document_count=len(texts),
        total_chars=total_chars,
        avg_text_length=mean([len(text) for text in texts]) if texts else 0.0,
    )

    for text in texts:
        summary.period_count += text.count(".")
        summary.question_count += text.count("?")
        summary.exclamation_count += text.count("!")
        summary.repeated_punctuation_count += len(re.findall(r"([.!?])\1+", text))
        summary.multi_space_count += len(MULTI_SPACE_RE.findall(text))
        summary.space_before_punctuation_count += len(SPACE_BEFORE_PUNCT_RE.findall(text))
        summary.hanja_pair_count += len(HANJA_PAIR_RE.findall(text))
        summary.recall_expression_count += len(RECALL_RE.findall(text))
        summary.experience_expression_count += len(EXPERIENCE_RE.findall(text))

        for ending in ENDING_PATTERNS:
            count = text.count(ending)
            if count:
                ending_counter[ending] += count
                _append_examples(ending_examples, _snippet_around(text, ending))

        for match in MULTI_SPACE_RE.finditer(text):
            _append_examples(spacing_examples, _snippet_around(text, match.group(0).strip()))
        for match in HANJA_PAIR_RE.finditer(text):
            _append_examples(hanja_examples, _snippet_around(text, match.group(0)))

    summary.period_per_100_chars = round(summary.period_count / total_chars * 100, 3) if total_chars else 0.0
    summary.ending_counts = dict(ending_counter.most_common())
    summary.spacing_examples = spacing_examples[:8]
    summary.hanja_examples = hanja_examples[:8]
    summary.ending_examples = ending_examples[:8]
    return summary


def write_outputs(summary: StyleFeatureSummary, markdown_path: str | Path, json_path: str | Path) -> None:
    markdown = Path(markdown_path)
    json_output = Path(json_path)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown.write_text(render_markdown_report(summary), encoding="utf-8")


def render_markdown_report(summary: StyleFeatureSummary) -> str:
    lines = [
        "# 문체 지표 리포트",
        "",
        "이 리포트는 안전 정제된 텍스트에서 문체 지표만 추출합니다. 원문 문장은 길게 인용하지 않습니다.",
        "",
        "## 기본 통계",
        "",
        f"- 문서 수: {summary.document_count}",
        f"- 총 글자 수: {summary.total_chars}",
        f"- 평균 길이: {summary.avg_text_length:.1f}",
        "",
        "## 문장 부호",
        "",
        f"- 마침표 개수: {summary.period_count}",
        f"- 100자당 마침표: {summary.period_per_100_chars}",
        f"- 물음표 개수: {summary.question_count}",
        f"- 느낌표 개수: {summary.exclamation_count}",
        f"- 반복 문장부호 패턴: {summary.repeated_punctuation_count}",
        "",
        "## 띄어쓰기",
        "",
        f"- 중간의 불필요한 다중 공백: {summary.multi_space_count}",
        f"- 문장부호 앞 공백: {summary.space_before_punctuation_count}",
    ]

    lines.extend(_example_block("짧은 띄어쓰기 사례", summary.spacing_examples))
    lines.extend(
        [
            "",
            "## 어휘와 표현",
            "",
            f"- 한자 병기 표현: {summary.hanja_pair_count}",
            f"- 회상형 표현: {summary.recall_expression_count}",
            f"- 경험 기반 표현: {summary.experience_expression_count}",
        ]
    )
    lines.extend(_example_block("짧은 한자 병기 사례", summary.hanja_examples))
    lines.extend(["", "## 종결어미", ""])
    if summary.ending_counts:
        for ending, count in summary.ending_counts.items():
            lines.append(f"- `{ending}`: {count}")
    else:
        lines.append("- 감지된 주요 종결어미 없음")
    lines.extend(_example_block("짧은 종결어미 사례", summary.ending_examples))
    lines.extend(
        [
            "",
            "## 캐릭터 프롬프트 반영 방향",
            "",
            "- 답변은 조언형으로 유지하되, 실제 사람이나 특정 집단을 직접 흉내 내지 않는다.",
            "- 마침표와 띄어쓰기의 어색함은 강도에 따라 제한적으로만 반영한다.",
            "- 한자 병기는 과하게 쓰지 않고, 문맥상 자연스러운 단어에만 붙인다.",
            "- 혐오, 집단 비하, 선동, 개인정보는 프롬프트와 출력에서 제외한다.",
        ]
    )
    return "\n".join(lines) + "\n"


def _example_block(title: str, examples: list[str]) -> list[str]:
    lines = ["", f"### {title}", ""]
    if not examples:
        lines.append("- 없음")
        return lines
    for example in examples:
        lines.append(f"- `{example}`")
    return lines


def _append_examples(examples: list[str], snippet: str) -> None:
    if snippet and snippet not in examples and len(examples) < 8:
        examples.append(snippet)


def _snippet_around(text: str, needle: str, window: int = 18) -> str:
    index = text.find(needle)
    if index < 0:
        return ""
    start = max(0, index - window)
    end = min(len(text), index + len(needle) + window)
    snippet = text[start:end].replace("\n", " ")
    if len(snippet) > 48:
        snippet = snippet[:45] + "..."
    return snippet


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract style features from clean_text.jsonl.")
    parser.add_argument("--input", default="data/processed/clean_text.jsonl")
    parser.add_argument("--markdown", default="analysis/style_report.md")
    parser.add_argument("--json", default="analysis/style_features.json")
    args = parser.parse_args()

    records = load_jsonl(args.input)
    summary = extract_style_features(records)
    write_outputs(summary, args.markdown, args.json)
    print(f"wrote {args.markdown} and {args.json}")


if __name__ == "__main__":
    main()
