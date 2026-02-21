# Workflow 1: Company Research

Reads companies from `list.csv`, scrapes each company's website, and summarizes the research with Claude. Run this whenever you want to populate research for companies before generating emails.

**Entry point:** `main.py`

---

## When to Use

- You have new companies in `list.csv` with `Emailed? = no` that haven't been researched yet
- You want to refresh research for existing companies

## Prerequisites

`.env` must have:

```
ANTHROPIC_API_KEY=...
CANDIDATE_NAME=Justin Mak
```

---

## How to Run

```bash
# Full run — outputs to output/<today's date>/
python main.py

# Limit to N companies (useful for testing)
python main.py --max-companies 10

# Custom batch name (creates output/feb_round2/)
python main.py --batch feb_round2

# Verify config without running
python main.py --check-config

# Verbose / debug logging
python main.py --verbose
```

Each run creates a separate folder under `output/` named after today's date (or `--batch`). Research results are isolated per run so batches never overwrite each other.

---

## Pipeline Stages

Stage 1 — Company Research
  Wait until theres email entries in list.csv with Emailed? = no, if not, do not start the workflow
           │
           ▼
  list.csv (Emailed? = no)
           │
           ▼
  WebScraper fetches company homepage → plain text
           │
           ▼
  Claude (claude-sonnet-4-5) summarizes into:
    • products / services
    • key features
    • recent news
    • one-paragraph overview
           │
           ▼
  output/<batch>/research/<Company>.json
```

### Stage 1 — Company Research (`outreach/research/`)

- Reads companies from `list.csv` where `Emailed?` is not set (i.e. not yet contacted)
- `WebScraper` fetches the company's homepage and extracts plain text
- `ResearchSummarizer` sends the content to Claude and parses the response into a `ResearchSummary` with:
  - `products_services` — what the company sells/does
  - `key_features` — notable technical or operational aspects
  - `recent_news` — recent announcements or launches
  - `summary_text` — one-paragraph overview
- Results are saved to `output/<batch>/research/` — each batch has its own isolated research folder
- If a company's website can't be scraped, Claude still generates a summary using general knowledge about the company

### Stage 2 — Email Generation (SEPARATE WORKFLOW)

Email templates are **not** generated here. After this workflow completes:

1. Add recruiter contacts to `recruiters/list.csv` with their `Job Type`
2. Run **Workflow 2** (`generate_from_csv.py`) to generate job-type-tailored templates

This ensures every template uses the correct candidate profile (coding / automation / data entry) rather than a generic default.

---

## Outputs

| Path | Description |
|------|-------------|
| `output/<batch>/research/<Company>.json` | Structured research per company |

`<batch>` defaults to today's date (`YYYY-MM-DD`) or the value of `--batch`.

---

## Notes

- Companies are sourced directly from `list.csv` — no job board scraping.
- Contacts are found and added to `recruiters/list.csv` manually before running Workflow 2.
