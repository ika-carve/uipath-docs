#!/usr/bin/env python3
"""
UiPath Documentation Scraper
Renders JS-heavy pages via Playwright, converts to Markdown.
Run on the jump server which has internet access.

Usage:
    python3 scrape.py                    # scrape all sections defined in SECTIONS
    python3 scrape.py --section maestro  # scrape single section
    python3 scrape.py --url https://...  # scrape single URL
    python3 scrape.py --update           # re-scrape pages older than --max-age-days
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("playwright not installed. Run: pip3 install playwright && playwright install chromium")

try:
    from markdownify import markdownify as md
except ImportError:
    sys.exit("markdownify not installed. Run: pip3 install markdownify")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "docs"
INDEX_FILE = BASE_DIR / "index.json"
LOG_FILE = BASE_DIR / "scrape.log"

BASE_URL = "https://docs.uipath.com"

# Sections to scrape: (slug, start_url, description)
# Add/remove sections here to control what gets downloaded.
SECTIONS = [
    ("automation-suite",        "/automation-suite/latest/installation-guide/overview",             "Automation Suite Installation"),
    ("automation-suite-ocp",    "/automation-suite/latest/installation-guide/openshift/overview",    "Automation Suite OpenShift"),
    ("orchestrator",            "/orchestrator/latest/user-guide/overview",                          "Orchestrator"),
    ("maestro",                 "/maestro/latest",                                                   "Maestro AI Orchestration"),
    ("ai-center",               "/ai-center/latest",                                                 "AI Center"),
    ("aifabric",                "/aifabric/latest",                                                  "AI Fabric"),
    ("context-grounding",       "/context-grounding/latest",                                         "Context Grounding / ECS"),
    ("uipathctl",               "/automation-suite/latest/installation-guide/uipathctl-reference",   "uipathctl CLI"),
    ("studio",                  "/studio/latest/studio/about-studio",                                "Studio"),
    ("robot",                   "/robot/latest",                                                     "UiPath Robot"),
]

# Pages to exclude (regex patterns matched against URL path)
EXCLUDE_PATTERNS = [
    r"/release-notes/",
    r"/changelog",
    r"#",          # anchor-only links
]

# Max pages per section (safety limit)
MAX_PAGES_PER_SECTION = 300

# Delay between requests (seconds) — be polite
REQUEST_DELAY = 1.5

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slug_from_url(url: str) -> str:
    """Convert URL to filesystem-safe slug."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_")
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", path)[:200]


def is_excluded(url: str) -> bool:
    for pat in EXCLUDE_PATTERNS:
        if re.search(pat, url):
            return True
    return False


def is_same_domain(url: str) -> bool:
    return urlparse(url).netloc in ("docs.uipath.com", "")


def clean_markdown(text: str, title: str, url: str) -> str:
    """Add frontmatter and clean up markdown."""
    # Strip cookie banner
    text = re.sub(r"We use cookies.*?Accept and continue", "", text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r"View cookie settings.*?Accept and continue", "", text, flags=re.DOTALL|re.IGNORECASE)
    # Strip raw JS blocks
    text = re.sub(r"!function\(\).*?}\(\)", "", text, flags=re.DOTALL)
    text = re.sub(r"\(function\(\).*?}\(\)\)", "", text, flags=re.DOTALL)
    # Remove excessive blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    # Remove navigation artifacts (common in doc sites)
    text = re.sub(r"^(Skip to|On this page|Table of contents|Breadcrumb).*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    text = text.strip()

    frontmatter = f"""---
title: {title}
url: {url}
scraped_at: {datetime.now(timezone.utc).isoformat()}
---

"""
    return frontmatter + text


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class DocScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        context = self._browser.new_context(
            user_agent="Mozilla/5.0 (compatible; UiPathDocBot/1.0; +internal-lab)",
            viewport={"width": 1280, "height": 900},
        )
        self._page = context.new_page()
        return self

    def __exit__(self, *_):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def fetch(self, url: str) -> tuple[str, str, list[str]]:
        """
        Fetch a URL, return (title, markdown_content, [outgoing_links]).
        """
        try:
            self._page.goto(url, wait_until="networkidle", timeout=30_000)
        except PWTimeout:
            log.warning(f"Timeout on {url}, trying with domcontentloaded")
            self._page.goto(url, wait_until="domcontentloaded", timeout=20_000)

        # Dismiss cookie banner if present
        for selector in [
            "button:has-text('Accept and continue')",
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
        ]:
            try:
                btn = self._page.locator(selector).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    time.sleep(0.3)
                    break
            except Exception:
                pass
        # Wait for main content
        for sel in ["article", "main", "[role=main]", ".markdown"]:
            try:
                self._page.wait_for_selector(sel, timeout=4000)
                break
            except Exception:
                pass
        time.sleep(0.8)  # Let any post-load JS settle

        # Extract title
        title = self._page.title() or url

        # Extract main content — try common doc selectors, fall back to body
        content_html = self._page.evaluate("""() => {
            const selectors = [
                'article',
                'main',
                '[class*="content"]',
                '[class*="markdown"]',
                '[class*="doc-content"]',
                '[role="main"]',
                '.page-content',
                '#content',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText && el.innerText.length > 200) {
                    return el.innerHTML;
                }
            }
            return document.body.innerHTML;
        }""")

        # Convert HTML → Markdown
        markdown = md(
            content_html,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style", "nav", "footer", "header", "button"],
        )

        # Collect internal links
        links = self._page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href)
                .filter(h => h.startsWith('https://docs.uipath.com'));
        }""")

        return title, markdown, list(set(links))


# ---------------------------------------------------------------------------
# Section crawl
# ---------------------------------------------------------------------------

def scrape_section(scraper: DocScraper, section_slug: str, start_url: str, description: str, index: dict) -> int:
    out_dir = OUTPUT_DIR / section_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    visited = set()
    queue = [start_url if start_url.startswith("http") else BASE_URL + start_url]
    scraped = 0

    log.info(f"=== Scraping section: {description} ({section_slug}) ===")

    while queue and scraped < MAX_PAGES_PER_SECTION:
        url = queue.pop(0)

        if url in visited:
            continue
        if is_excluded(url):
            continue
        if not is_same_domain(url):
            continue

        visited.add(url)

        # Only scrape pages within this section's path
        parsed_start = urlparse(start_url if start_url.startswith("http") else BASE_URL + start_url)
        parsed_url = urlparse(url)
        section_base = "/" + parsed_start.path.strip("/").split("/")[0]
        if not parsed_url.path.startswith(section_base) and not parsed_url.path.startswith(parsed_start.path.rsplit("/", 1)[0]):
            continue

        file_slug = slug_from_url(url)
        out_path = out_dir / f"{file_slug}.md"

        log.info(f"  Fetching [{scraped+1}]: {url}")
        try:
            title, content, links = scraper.fetch(url)
        except Exception as e:
            log.error(f"  Error fetching {url}: {e}")
            time.sleep(REQUEST_DELAY * 2)
            continue

        # Save markdown
        final_md = clean_markdown(content, title, url)
        out_path.write_text(final_md, encoding="utf-8")

        # Update index
        index[url] = {
            "title": title,
            "section": section_slug,
            "file": str(out_path.relative_to(BASE_DIR)),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "word_count": len(content.split()),
        }

        scraped += 1
        # Queue new links
        for link in links:
            if link not in visited and link not in queue:
                queue.append(link)

        time.sleep(REQUEST_DELAY)

    log.info(f"  Section {section_slug}: {scraped} pages saved to {out_dir}")
    return scraped


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------

def build_search_index(index: dict):
    """
    Build a lightweight full-text search index:
    one JSON file per section with titles + first 500 chars of each page.
    Makes it easy for Claude (or grep) to find relevant pages.
    """
    by_section: dict[str, list] = {}
    for url, meta in index.items():
        s = meta["section"]
        by_section.setdefault(s, []).append(meta)

    search_index = []
    for url, meta in index.items():
        fpath = BASE_DIR / meta["file"]
        snippet = ""
        if fpath.exists():
            text = fpath.read_text(encoding="utf-8")
            # Skip frontmatter (first 5 lines)
            lines = text.splitlines()[5:]
            snippet = " ".join(lines)[:500].replace("\n", " ")
        search_index.append({
            "url": url,
            "title": meta["title"],
            "section": meta["section"],
            "file": meta["file"],
            "snippet": snippet,
        })

    search_path = BASE_DIR / "search_index.json"
    search_path.write_text(json.dumps(search_index, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"Search index written: {search_path} ({len(search_index)} entries)")


def build_toc():
    """Build a human+LLM-readable table of contents in Markdown."""
    index_data = {}
    if INDEX_FILE.exists():
        index_data = json.loads(INDEX_FILE.read_text())

    lines = [
        "# UiPath Documentation — Table of Contents",
        f"\n_Scraped: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n",
    ]

    by_section: dict[str, list] = {}
    for url, meta in index_data.items():
        by_section.setdefault(meta["section"], []).append((meta["title"], url, meta["file"]))

    for section_slug, pages in sorted(by_section.items()):
        lines.append(f"\n## {section_slug}\n")
        for title, url, fpath in sorted(pages, key=lambda x: x[0]):
            lines.append(f"- [{title}]({fpath})  \n  _{url}_")

    toc_path = BASE_DIR / "TOC.md"
    toc_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"TOC written: {toc_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_index() -> dict:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return {}


def save_index(index: dict):
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Scrape UiPath docs to Markdown")
    parser.add_argument("--section", help="Scrape only this section slug")
    parser.add_argument("--url", help="Scrape a single URL")
    parser.add_argument("--update", action="store_true", help="Re-scrape stale pages")
    parser.add_argument("--max-age-days", type=int, default=30, help="Days before a page is considered stale (default: 30)")
    parser.add_argument("--list-sections", action="store_true", help="List configured sections and exit")
    parser.add_argument("--toc-only", action="store_true", help="Rebuild TOC and search index without scraping")
    args = parser.parse_args()

    if args.list_sections:
        print("\nConfigured sections:")
        for slug, url, desc in SECTIONS:
            print(f"  {slug:<30} {desc}")
            print(f"  {'':30} {BASE_URL}{url}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    index = load_index()

    if args.toc_only:
        build_search_index(index)
        build_toc()
        return

    sections_to_run = SECTIONS

    if args.section:
        sections_to_run = [s for s in SECTIONS if s[0] == args.section]
        if not sections_to_run:
            sys.exit(f"Unknown section: {args.section}. Use --list-sections to see options.")

    if args.url:
        # Single URL mode
        with DocScraper() as scraper:
            log.info(f"Single URL: {args.url}")
            title, content, _ = scraper.fetch(args.url)
            slug = slug_from_url(args.url)
            out = OUTPUT_DIR / "custom" / f"{slug}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(clean_markdown(content, title, args.url), encoding="utf-8")
            log.info(f"Saved: {out}")
        return

    with DocScraper() as scraper:
        for section_slug, start_url, description in sections_to_run:
            scrape_section(scraper, section_slug, start_url, description, index)
            save_index(index)  # Save after each section in case of crash

    build_search_index(index)
    build_toc()
    save_index(index)
    log.info("Done.")


if __name__ == "__main__":
    main()
