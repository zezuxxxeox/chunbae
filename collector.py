from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

from clean_text import clean_record, mask_pii
from config import CollectorConfig, SiteTarget, expand_board_urls, load_config
from database import DEFAULT_DB_PATH, CorpusStore
from html_text import extract_links, extract_readable_text, extract_site_records


def collect(
    config_path: str = "sites.yaml",
    db_path: str | Path | None = DEFAULT_DB_PATH,
    target_records: int | None = None,
) -> Path | None:
    config = load_config(config_path)
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = config.raw_dir / f"raw_{timestamp}.jsonl"
    store = CorpusStore(db_path) if db_path else None

    written = 0
    try:
        with output_path.open("w", encoding="utf-8") as output:
            for target in config.targets:
                if target_records is not None and written >= target_records:
                    break
                if not target.terms_ok:
                    _log_failure(config, target.name, "", "terms_ok is false; skipped", store)
                    continue
                remaining = None if target_records is None else target_records - written
                written += _collect_target(config, target, output, store, remaining)
    finally:
        if store:
            store.close()

    if written == 0:
        return None
    return output_path


def _collect_target(
    config: CollectorConfig,
    target: SiteTarget,
    output,
    store: CorpusStore | None,
    remaining_limit: int | None,
) -> int:
    robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
    candidate_urls: list[str] = []
    written = 0

    for board_url in expand_board_urls(target):
        if remaining_limit is not None and written >= remaining_limit:
            break
        if not _robots_allowed(config, robots_cache, board_url):
            _log_failure(config, target.name, board_url, "blocked by robots.txt", store)
            continue
        try:
            html = _fetch(board_url, config.user_agent, render_js=target.render_js)
        except Exception as exc:
            _log_failure(config, target.name, board_url, f"fetch failed: {exc}", store)
            continue

        links = extract_links(html, board_url)
        filtered = [_normalize_url(link) for link in links if _matches_target(link, target)]
        candidate_urls.extend(filtered)
        if store:
            store.enqueue_urls(target.name, filtered)
        time.sleep(target.sleep_interval)

    seen: set[str] = set()
    for url in candidate_urls:
        if url in seen:
            continue
        seen.add(url)
        max_items = target.max_items
        if remaining_limit is not None:
            max_items = min(max_items, remaining_limit)
        if written >= max_items:
            break
        if not _robots_allowed(config, robots_cache, url):
            _log_failure(config, target.name, url, "blocked by robots.txt", store)
            continue
        try:
            html = _fetch(url, config.user_agent, render_js=target.render_js)
            site_records = extract_site_records(url, html)
            if not site_records:
                _log_failure(config, target.name, url, "empty extracted text", store)
                continue
            for block_index, (content_type, extracted_text) in enumerate(site_records):
                if written >= max_items:
                    break
                text, pii_flags = mask_pii(extracted_text)
                if not text:
                    continue
                record_url = url if block_index == 0 else f"{url}#block-{block_index}"
                raw_record = {
                    "source_site": target.name,
                    "post_url": record_url,
                    "content_type": content_type or target.content_type,
                    "text": text,
                    "text_length": len(text),
                    "pii_masked_at_collection": pii_flags,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }
                cleaned_record = clean_record(raw_record)
                output.write(json.dumps(raw_record, ensure_ascii=False) + "\n")
                if store:
                    store.upsert_document(raw_record, cleaned_record)
                written += 1
        except Exception as exc:
            _log_failure(config, target.name, url, f"post fetch failed: {exc}", store)
        time.sleep(target.sleep_interval)

    return written


def _fetch(url: str, user_agent: str, render_js: bool = False) -> str:
    if render_js:
        return _fetch_with_playwright(url)

    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=20) as response:
        content_type = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(content_type, errors="replace")


def _fetch_with_playwright(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()
        return html


def _robots_allowed(
    config: CollectorConfig,
    robots_cache: dict[str, urllib.robotparser.RobotFileParser | None],
    url: str,
) -> bool:
    parsed = urllib.parse.urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if root not in robots_cache:
        robots_url = urllib.parse.urljoin(root, "/robots.txt")
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
        except (urllib.error.URLError, OSError):
            robots_cache[root] = None
        else:
            robots_cache[root] = parser

    parser_or_none = robots_cache[root]
    if parser_or_none is None:
        return config.allow_if_robots_unavailable
    return parser_or_none.can_fetch(config.user_agent, url)


def _matches_target(url: str, target: SiteTarget) -> bool:
    if target.include_url_patterns and not any(re.search(pattern, url) for pattern in target.include_url_patterns):
        return False
    if target.exclude_url_patterns and any(re.search(pattern, url) for pattern in target.exclude_url_patterns):
        return False
    return True


def _normalize_url(url: str) -> str:
    return urllib.parse.urldefrag(url)[0]


def _log_failure(
    config: CollectorConfig,
    source_site: str,
    url: str,
    reason: str,
    store: CorpusStore | None = None,
) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    path = config.log_dir / "collector_failures.jsonl"
    with path.open("a", encoding="utf-8") as log:
        log.write(
            json.dumps(
                {
                    "source_site": source_site,
                    "post_url": url,
                    "reason": reason,
                    "logged_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    if store:
        store.log_failure(source_site, url, reason)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public community text with robots.txt checks.")
    parser.add_argument("--config", default="sites.yaml")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--no-db", action="store_true")
    parser.add_argument("--target-records", type=int, default=0)
    args = parser.parse_args()
    output = collect(
        args.config,
        db_path=None if args.no_db else args.db,
        target_records=args.target_records or None,
    )
    if output:
        print(f"wrote raw records to {output}")
    else:
        print("no records collected; check logs/collector_failures.jsonl")


if __name__ == "__main__":
    main()
