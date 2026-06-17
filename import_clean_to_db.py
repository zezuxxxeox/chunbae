from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

from database import CorpusStore, DEFAULT_DB_PATH


def import_clean_jsonl(patterns: list[str], db_path: str | Path = DEFAULT_DB_PATH) -> int:
    store = CorpusStore(db_path)
    count = 0
    for pattern in patterns:
        for path_text in glob.glob(pattern):
            path = Path(path_text)
            with path.open("r", encoding="utf-8") as source:
                records = [json.loads(line) for line in source if line.strip()]
            count += store.import_clean_records(records)
    store.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import clean JSONL records into SQLite corpus DB.")
    parser.add_argument("--input", nargs="+", default=["data/processed/clean_text.jsonl"])
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    count = import_clean_jsonl(args.input, args.db)
    print(f"imported {count} records into {args.db}")


if __name__ == "__main__":
    main()
