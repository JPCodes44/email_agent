#!/usr/bin/env python3
"""Workflow 1: Company Research — scrape websites and summarize with Claude."""

import sys, os, json, argparse, logging
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, filter_not_emailed
from shared.company_utils import filename_safe

import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic

log = logging.getLogger("workflows")


def scrape_website(url: str) -> str:
    """Fetch a URL and return plain text content."""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:8000]  # truncate to avoid huge prompts
    except Exception as e:
        log.warning(f"Could not scrape {url}: {e}")
        return ""


def summarize_company(client: Anthropic, company: str, website_text: str) -> dict:
    """Use Claude to summarize a company's website content."""
    if website_text:
        user_prompt = (
            f"Here is text scraped from {company}'s website:\n\n{website_text}\n\n"
            f"Please summarize this company. Return a JSON object with these keys:\n"
            f'- "products_services": what the company sells or does\n'
            f'- "key_features": notable technical or operational aspects\n'
            f'- "recent_news": any recent announcements or launches mentioned\n'
            f'- "summary_text": a one-paragraph overview'
        )
    else:
        user_prompt = (
            f"I couldn't scrape {company}'s website. Based on your general knowledge, "
            f"please summarize this company. Return a JSON object with these keys:\n"
            f'- "products_services": what the company sells or does\n'
            f'- "key_features": notable technical or operational aspects\n'
            f'- "recent_news": any recent announcements or launches (if known)\n'
            f'- "summary_text": a one-paragraph overview'
        )

    resp = client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text

    # Try to parse JSON from the response
    try:
        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return {"summary_text": text, "products_services": "", "key_features": "", "recent_news": ""}


def check_config():
    """Verify required configuration is present."""
    issues = []
    if not config.ANTHROPIC_API_KEY:
        issues.append("ANTHROPIC_API_KEY is not set")

    csv_path = config.WORKFLOWS_DIR / "list.csv"
    if not csv_path.exists():
        issues.append(f"list.csv not found at {csv_path}")

    if issues:
        for i in issues:
            print(f"  ✗ {i}")
        return False
    else:
        print("  ✓ All config checks passed")
        return True


def main():
    parser = argparse.ArgumentParser(description="Company research workflow")
    parser.add_argument("--max-companies", type=int, default=None, help="Limit number of companies")
    parser.add_argument("--batch", default=None, help="Batch name (default: today's date)")
    parser.add_argument("--check-config", action="store_true", help="Verify config and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.check_config:
        sys.exit(0 if check_config() else 1)

    batch_name = args.batch or date.today().isoformat()
    output_dir = config.OUTPUT_DIR / batch_name / "research"
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = config.WORKFLOWS_DIR / "list.csv"
    if not csv_path.exists():
        log.error(f"list.csv not found at {csv_path}")
        sys.exit(1)

    rows = filter_not_emailed(read_csv(csv_path))
    if not rows:
        log.info("No companies to research (all marked as emailed)")
        return

    if args.max_companies:
        rows = rows[:args.max_companies]

    log.info(f"Researching {len(rows)} companies → {output_dir}")

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    for row in rows:
        company = row.get("Company", "").strip()
        website = row.get("Website", "").strip()
        if not company:
            continue

        try:
            log.info(f"Researching: {company}")
            website_text = scrape_website(website) if website else ""
            summary = summarize_company(client, company, website_text)
            summary["company"] = company
            summary["website"] = website

            out_file = output_dir / f"{filename_safe(company)}.json"
            out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            log.info(f"  ✓ Saved {out_file.name}")
        except Exception as e:
            log.error(f"  ✗ Failed for {company}: {e}")


if __name__ == "__main__":
    main()
