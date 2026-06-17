from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from database import CorpusStore, DEFAULT_DB_PATH
from style_features import extract_style_features, render_markdown_report, write_outputs


PROFILE_NAME = "ajoossi_style_v1"
STYLE_MODEL_PATH = Path("analysis/style_model.json")

SAFE_PHRASE_PATTERNS = [
    "제가 보기엔",
    "경험상",
    "요즘 젊은 분들은",
    "사람 사는 게",
    "결국은",
    "기본이 중요",
    "하는 게 맞습니다",
    "하시길 바랍니다",
    "라는 얘기입니다",
    "그렇게 보시면 됩니다",
]
ENDING_RE = re.compile(r"([가-힣]{1,10}(?:합니다|입니다|됩니다|바랍니다|맞습니다|겁니다|얘기입니다)\.)")
INFORMAL_ENDING_RE = re.compile(r"([가-힣]{1,12}(?:나|노|라|고|네|제|께|먹어|가라|와|해라|시라|된다|있나)\??)")
CHAT_MARKERS = ["ㅋㅋ", "ㅎㅎ", "ㅜ", "ㅠ", "ㅡㅡ", "~~", "~", "?"]


def train_style_model(
    db_path: str | Path = DEFAULT_DB_PATH,
    limit: int | None = None,
    source_site: str | None = None,
    profile_name: str = PROFILE_NAME,
    style_model_path: str | Path = STYLE_MODEL_PATH,
    report_path: str | Path = "analysis/style_report.md",
    features_path: str | Path = "analysis/style_features.json",
) -> dict:
    store = CorpusStore(db_path)
    records = _load_training_records(store, limit=limit, source_site=source_site)
    summary = extract_style_features(records)
    prompt_rules = _build_prompt_rules(records, asdict(summary))

    model = {
        "profile_name": profile_name,
        "document_count": len(records),
        "features": asdict(summary),
        "prompt_rules": prompt_rules,
    }

    model_output = Path(style_model_path)
    model_output.parent.mkdir(parents=True, exist_ok=True)
    model_output.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    write_outputs(summary, report_path, features_path)
    store.save_style_profile(profile_name, len(records), asdict(summary), prompt_rules)
    store.close()
    return model


def _load_training_records(
    store: CorpusStore,
    limit: int | None = None,
    source_site: str | None = None,
) -> list[dict]:
    if source_site is None:
        return list(store.iter_clean_records(limit=limit))

    query = """
        SELECT source_site, post_url, content_type, clean_text AS text, text_length
        FROM documents
        WHERE clean_text <> '' AND source_site = ?
        ORDER BY id
    """
    params: tuple[str, int] | tuple[str]
    params = (source_site,)
    if limit is not None:
        query += " LIMIT ?"
        params = (source_site, limit)
    return [dict(row) for row in store.connection.execute(query, params)]


def _build_prompt_rules(records: list[dict], features: dict) -> dict:
    texts = [str(record.get("text", "")) for record in records]
    phrase_counts = {
        phrase: sum(text.count(phrase) for text in texts)
        for phrase in SAFE_PHRASE_PATTERNS
    }
    ending_counter: Counter[str] = Counter()
    informal_ending_counter: Counter[str] = Counter()
    marker_counter: Counter[str] = Counter()
    short_message_count = 0
    for text in texts:
        ending_counter.update(ENDING_RE.findall(text))
        informal_ending_counter.update(INFORMAL_ENDING_RE.findall(text))
        for marker in CHAT_MARKERS:
            marker_counter[marker] += text.count(marker)
        if len(text.strip()) <= 20:
            short_message_count += 1

    period_density = float(features.get("period_per_100_chars", 0.0))
    multi_space_count = int(features.get("multi_space_count", 0))
    hanja_pair_count = int(features.get("hanja_pair_count", 0))
    question_count = int(features.get("question_count", 0))
    total_docs = max(1, len(records))

    return {
        "period_style": "frequent" if period_density >= 2.0 else "moderate",
        "spacing_style": "irregular" if multi_space_count > 0 else "mostly_regular",
        "question_style": "frequent_short_questions" if question_count / total_docs >= 0.08 else "moderate",
        "hanja_style": "occasional" if hanja_pair_count > 0 else "rare",
        "message_length_style": "short_chatty" if short_message_count / total_docs >= 0.35 else "mixed",
        "safe_phrase_counts": {key: count for key, count in phrase_counts.items() if count > 0},
        "top_endings": dict(ending_counter.most_common(20)),
        "top_informal_endings": dict(informal_ending_counter.most_common(20)),
        "chat_marker_counts": dict(marker_counter.most_common()),
        "style_anchor_examples": _select_style_anchors(records),
        "generation_rules": [
            "학습된 원문 문장을 복사하지 말고 문체 지표만 반영한다.",
            "특정 실존 인물 또는 특정 커뮤니티 이용자를 흉내 내지 않는다.",
            "혐오, 집단 비하, 개인정보, 위협 표현은 제거한다.",
            "짧은 생활형 조언, 반문, 간단한 지시문, 불규칙한 공백을 스타일 지표로만 반영한다.",
        ],
    }


def _select_style_anchors(records: list[dict], limit: int = 12) -> list[str]:
    """짧은 종결어미 '조각'만 모은다. 원문 문장을 통째로 인용하지 않기 위해
    문장 전체가 아니라 종결어미 패턴만 뽑는다."""
    anchors: list[str] = []
    banned_fragments = ["[", "]", "@", "http"]
    for record in records:
        text = " ".join(str(record.get("text", "")).split())
        for ending in ENDING_RE.findall(text):
            ending = ending.strip()
            if not ending or len(ending) > 14:
                continue
            if any(fragment in ending for fragment in banned_fragments):
                continue
            if ending in anchors:
                continue
            anchors.append(ending)
            if len(anchors) >= limit:
                return anchors
    return anchors


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a safe style profile from the SQLite corpus.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--source-site", default="")
    parser.add_argument("--profile-name", default=PROFILE_NAME)
    parser.add_argument("--style-model", default=str(STYLE_MODEL_PATH))
    parser.add_argument("--report", default="analysis/style_report.md")
    parser.add_argument("--features", default="analysis/style_features.json")
    args = parser.parse_args()
    model = train_style_model(
        args.db,
        limit=args.limit or None,
        source_site=args.source_site or None,
        profile_name=args.profile_name,
        style_model_path=args.style_model,
        report_path=args.report,
        features_path=args.features,
    )
    print(f"trained {model['profile_name']} from {model['document_count']} documents")


if __name__ == "__main__":
    main()
