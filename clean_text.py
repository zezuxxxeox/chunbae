from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path
from typing import Any

from safety_filter import SafetyFilter


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?82[-.\s]?)?0?1[016789][-\s.]?\d{3,4}[-.\s.]?\d{4}(?!\d)|"
    r"(?<!\d)0\d{1,2}[-.\s.]?\d{3,4}[-.\s.]?\d{4}(?!\d)"
)
ACCOUNT_RE = re.compile(
    r"(?:(계좌|은행|입금|송금|예금주)[^\n]{0,12})?"
    r"(?<!\d)\d{2,6}[-\s]\d{2,6}[-\s]\d{2,8}(?!\d)"
)
ADDRESS_RE = re.compile(
    r"[가-힣]{2,}(?:시|도)\s+[가-힣0-9]{1,}(?:구|군|시)\s+"
    r"[가-힣0-9\s]{1,30}(?:로|길)\s*\d{0,5}"
)
CAR_PLATE_RE = re.compile(r"(?<!\d)\d{2,3}[가-힣]\s?\d{4}(?!\d)")
NICK_RE = re.compile(r"(?m)^(닉네임|닉|작성자|아이디|ID)\s*[:=]\s*\S+")
COPYPASTA_HINT_RE = re.compile(r"(무단전재|재배포 금지|Copyright|All rights reserved)", re.IGNORECASE)


def mask_pii(text: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    replacements = [
        ("email", EMAIL_RE, "[EMAIL]"),
        ("phone", PHONE_RE, "[PHONE]"),
        ("account", ACCOUNT_RE, "[ACCOUNT]"),
        ("address", ADDRESS_RE, "[ADDRESS]"),
        ("car_plate", CAR_PLATE_RE, "[CAR_PLATE]"),
        ("nickname", NICK_RE, r"\1: [NICKNAME]"),
    ]
    masked = text
    for flag, pattern, replacement in replacements:
        if pattern.search(masked):
            flags.append(flag)
            masked = pattern.sub(replacement, masked)
    return masked, flags


def preserve_style_clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    line_counts: dict[str, int] = {}
    kept_lines: list[str] = []
    for line in text.split("\n"):
        if COPYPASTA_HINT_RE.search(line):
            continue
        key = line.strip()
        if key:
            line_counts[key] = line_counts.get(key, 0) + 1
        if key and line_counts[key] > 3:
            continue
        kept_lines.append(line.rstrip())

    return "\n".join(kept_lines).strip()


def clean_record(record: dict[str, Any], safety_filter: SafetyFilter | None = None) -> dict[str, Any]:
    safety_filter = safety_filter or SafetyFilter()
    original = str(record.get("text", ""))
    masked, pii_flags = mask_pii(original)
    minimally_cleaned = preserve_style_clean(masked)
    safety = safety_filter.sanitize(minimally_cleaned)
    cleaned = {
        "source_site": record.get("source_site", ""),
        "post_url": record.get("post_url", ""),
        "content_type": record.get("content_type", "post"),
        "text": safety.text,
        "text_length": len(safety.text),
        "pii_masked": pii_flags,
        "safety_flags": safety.flags,
    }
    return cleaned


def clean_files(input_patterns: list[str], output_path: str | Path) -> int:
    paths: list[Path] = []
    for pattern in input_patterns:
        expanded = [Path(p) for p in glob.glob(pattern)]
        paths.extend(expanded or [Path(pattern)])

    safety_filter = SafetyFilter()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with output.open("w", encoding="utf-8") as out:
        for path in paths:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    cleaned = clean_record(record, safety_filter)
                    if cleaned["text"]:
                        out.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
                        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Mask PII and create clean_text.jsonl.")
    parser.add_argument("--input", nargs="+", default=["data/raw/*.jsonl"])
    parser.add_argument("--output", default="data/processed/clean_text.jsonl")
    args = parser.parse_args()
    count = clean_files(args.input, args.output)
    print(f"wrote {count} records to {args.output}")


if __name__ == "__main__":
    main()
