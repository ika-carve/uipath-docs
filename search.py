#!/usr/bin/env python3
"""
search.py — Find relevant UiPath doc pages given a query.

Usage:
    python3 search.py "openshift persistent volume"
    python3 search.py "ai center model deployment" --section ai-center
    python3 search.py "uipathctl manifest apply" --show        # also print file content
    python3 search.py "maestro agent" --top 10

How it works:
    1. Keyword match against titles and snippets in search_index.json
    2. Score = title_hits * 3 + snippet_hits
    3. Print top-N results with file path, so you can `cat` the markdown.
"""

import argparse
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
INDEX_FILE = BASE_DIR / "search_index.json"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9\-_]+", text.lower())


def score(entry: dict, tokens: list[str]) -> int:
    title_tokens = tokenize(entry.get("title", ""))
    snippet_tokens = tokenize(entry.get("snippet", ""))
    s = 0
    for tok in tokens:
        s += title_tokens.count(tok) * 3
        s += snippet_tokens.count(tok)
    return s


def main():
    parser = argparse.ArgumentParser(description="Search UiPath docs")
    parser.add_argument("query", nargs="+", help="Search terms")
    parser.add_argument("--section", help="Limit to section slug")
    parser.add_argument("--top", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--show", action="store_true", help="Print content of top result")
    args = parser.parse_args()

    if not INDEX_FILE.exists():
        sys.exit(f"search_index.json not found at {INDEX_FILE}. Run scrape.py first.")

    index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    tokens = tokenize(" ".join(args.query))

    if args.section:
        index = [e for e in index if e.get("section") == args.section]

    scored = [(score(e, tokens), e) for e in index]
    scored = [(s, e) for s, e in scored if s > 0]
    scored.sort(key=lambda x: -x[0])

    if not scored:
        print("No results found.")
        return

    print(f"\nTop {min(args.top, len(scored))} results for: {' '.join(args.query)}\n")
    for i, (sc, entry) in enumerate(scored[: args.top]):
        print(f"  [{i+1}] {entry['title']}")
        print(f"       Section : {entry['section']}")
        print(f"       File    : {BASE_DIR / entry['file']}")
        print(f"       URL     : {entry['url']}")
        print(f"       Score   : {sc}")
        print(f"       Snippet : {entry['snippet'][:120]}...")
        print()

    if args.show and scored:
        _, top = scored[0]
        fpath = BASE_DIR / top["file"]
        if fpath.exists():
            print("=" * 72)
            print(fpath.read_text(encoding="utf-8")[:4000])
            print("=" * 72)


if __name__ == "__main__":
    main()
