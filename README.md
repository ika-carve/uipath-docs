# UiPath Docs Scraper

Downloads UiPath documentation fra `docs.uipath.com` (JS-renderet via Playwright)
og gemmer det som Markdown-filer, optimeret til LLM-opslag.

## Filer

```
uipath-docs/
├── scrape.py          # Hoved-scraper
├── update.py          # Inkrementel opdatering
├── search.py          # Søg i downloadet dok
├── setup.sh           # Installationsscript til jump server
├── index.json         # Metadata for alle scrapede sider
├── search_index.json  # Søgeindeks (titler + snippets)
├── TOC.md             # Inholdsfortegnelse (Markdown)
├── scrape.log         # Log
└── docs/
    ├── automation-suite/
    │   └── *.md
    ├── maestro/
    │   └── *.md
    ├── ai-center/
    │   └── *.md
    └── ...
```

## Installation (på jump server)

```bash
# Kopier til jump server
scp -r uipath-docs-scraper/ labadmin@20.101.72.21:/tmp/

# SSH til jump
ssh labadmin@20.101.72.21
cd /tmp/uipath-docs-scraper

# Kør setup (installerer venv, playwright/chromium, cron job)
sudo bash setup.sh
```

## Første kørsel

```bash
cd /opt/uipath-docs

# Scrape én sektion for at teste (5-10 min)
venv/bin/python3 scrape.py --section maestro

# Scrape alle sektioner (30-60 min afhængig af indholdet)
venv/bin/python3 scrape.py

# Tilføj en enkelt side manuelt
venv/bin/python3 scrape.py --url https://docs.uipath.com/automation-suite/latest/.../some-page
```

## Opdatering

```bash
# Opdater sider ældre end 30 dage
venv/bin/python3 update.py

# Opdater sider ældre end 7 dage
venv/bin/python3 update.py --max-age-days 7

# Tving fuld gen-scrape
venv/bin/python3 update.py --force

# Opdater kun én sektion
venv/bin/python3 update.py --section ai-center
```

Automatisk cron job kører hver søndag kl. 03:00.

## Søgning

```bash
# Find relevante sider
venv/bin/python3 search.py "openshift storage class nfs"

# Søg kun i én sektion
venv/bin/python3 search.py "model deployment" --section ai-center

# Vis indhold af top-resultat
venv/bin/python3 search.py "uipathctl manifest apply" --show

# Vis top-10 resultater
venv/bin/python3 search.py "maestro agent orchestration" --top 10

# Læs en specifik side
cat docs/maestro/automation-suite_latest_maestro_something.md
```

## Tilføj nye sektioner

Rediger `SECTIONS` listen i `scrape.py`:

```python
SECTIONS = [
    ("min-sektion", "/url/til/startside", "Beskrivelse"),
    # ... eksisterende sektioner
]
```

Kør derefter:
```bash
venv/bin/python3 scrape.py --section min-sektion
# eller
venv/bin/python3 update.py  # opdager automatisk nye sektioner
```

## Markdown-format

Hver side har YAML frontmatter:

```markdown
---
title: Overview
url: https://docs.uipath.com/maestro/latest/overview
scraped_at: 2026-05-19T10:00:00+00:00
---

# Overview

Indhold her...
```

## Konfiguration

I `scrape.py`:

| Konstant | Standard | Beskrivelse |
|---|---|---|
| `MAX_PAGES_PER_SECTION` | 300 | Maks sider per sektion |
| `REQUEST_DELAY` | 1.5 sek | Pause mellem requests |
| `EXCLUDE_PATTERNS` | release-notes m.fl. | URL-mønstre der springes over |
