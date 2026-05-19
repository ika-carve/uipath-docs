#!/usr/bin/env python3
"""
update.py — Incremental update of UiPath docs.

Re-scrapes:
  - Pages missing from disk
  - Pages older than --max-age-days (default 30)
  - Pages in sections added to scrape.py since last run

Usage:
    python3 update.py                    # default 30 days
    python3 update.py --max-age-days 7   # weekly refresh
    python3 update.py --section maestro  # update one section only
    python3 update.py --force            # re-scrape everything
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from scrape import (
    DocScraper, SECTIONS, OUTPUT_DIR, INDEX_FILE,
    scrape_section, build_search_index, build_toc,
    log, save_index, load_index, BASE_URL,
    slug_from_url, clean_markdown, is_excluded, is_same_domain,
    REQUEST_DELAY, MAX_PAGES_PER_SECTION
)
import time


def is_stale(meta: dict, max_age: timedelta) -> bool:
    try:
        scraped = datetime.fromisoformat(meta["scraped_at"])
        return (datetime.now(timezone.utc) - scraped) > max_age
    except Exception:
        return True


def main():
    parser = argparse.ArgumentParser(description="Incremental UiPath docs update")
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--section", help="Only update this section")
    parser.add_argument("--force", action="store_true", help="Re-scrape all pages")
    args = parser.parse_args()

    max_age = timedelta(days=args.max_age_days)
    index = load_index()

    # Determine which sections to run
    sections_to_run = SECTIONS
    if args.section:
        sections_to_run = [s for s in SECTIONS if s[0] == args.section]

    if args.force:
        log.info("Force mode: re-scraping all sections")
        with DocScraper() as scraper:
            for slug, url, desc in sections_to_run:
                scrape_section(scraper, slug, url, desc, index)
                save_index(index)
    else:
        # Find stale or missing pages per section
        known_by_section: dict[str, set] = {}
        for url, meta in index.items():
            known_by_section.setdefault(meta["section"], set()).add(url)

        with DocScraper() as scraper:
            for slug, start_url, desc in sections_to_run:
                # Pages in this section that are stale or file is missing
                stale_urls = []
                for url, meta in index.items():
                    if meta["section"] != slug:
                        continue
                    fpath = BASE_DIR / meta["file"]
                    if not fpath.exists() or is_stale(meta, max_age) or args.force:
                        stale_urls.append(url)

                if stale_urls:
                    log.info(f"Section {slug}: {len(stale_urls)} stale pages, re-scraping")
                    for url in stale_urls:
                        if is_excluded(url):
                            continue
                        log.info(f"  Re-fetching: {url}")
                        try:
                            title, content, _ = scraper.fetch(url)
                            file_slug = slug_from_url(url)
                            out_dir = OUTPUT_DIR / slug
                            out_dir.mkdir(parents=True, exist_ok=True)
                            out_path = out_dir / f"{file_slug}.md"
                            out_path.write_text(clean_markdown(content, title, url), encoding="utf-8")
                            from datetime import datetime, timezone
                            index[url] = {
                                "title": title,
                                "section": slug,
                                "file": str(out_path.relative_to(BASE_DIR)),
                                "scraped_at": datetime.now(timezone.utc).isoformat(),
                                "word_count": len(content.split()),
                            }
                            time.sleep(REQUEST_DELAY)
                        except Exception as e:
                            log.error(f"  Error: {e}")
                    save_index(index)
                else:
                    # Section not scraped at all yet → full scrape
                    if slug not in known_by_section:
                        log.info(f"Section {slug}: new section, scraping from scratch")
                        scrape_section(scraper, slug, start_url, desc, index)
                        save_index(index)
                    else:
                        log.info(f"Section {slug}: all pages up to date")

    build_search_index(index)
    build_toc()
    log.info("Update complete.")


if __name__ == "__main__":
    main()
