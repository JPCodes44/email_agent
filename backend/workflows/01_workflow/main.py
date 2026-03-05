#!/usr/bin/env python3
"""Workflow 1: Company Research — single Perplexity deep research call per company."""

import sys, json, argparse, logging
from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, filter_not_emailed
from shared.company_utils import filename_safe
from shared.llm import create_perplexity_client, chat_perplexity

log = logging.getLogger("workflows")

COMPANY_SCHEMA_STR = """\
- "products_services": string — what the company sells or does, including specific product names and customers
- "key_features": string — 2-3 SPECIFIC things that make this company unique — concrete details
- "recent_news": string — 2-3 SPECIFIC recent announcements, blog posts, product updates, funding rounds, or initiatives — cite actual things with dates if possible
- "tech_stack": string — technologies, frameworks, or technical approaches mentioned on their site, blog, or job postings
- "culture_values": string — company culture, mission, values, or notable initiatives (DEI, open source, community)
- "summary_text": string — a two-paragraph overview demonstrating deep knowledge — include 2-3 specific details
Each value must be a plain string. If unknown, use an empty string ""."""


def domain_from_email(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else ""


def research_company(perplexity_client, company: str, website: str) -> dict:
    prompt = f"""Research the company "{company}" ({website}) in depth using web search.

Find and extract:
1. What they sell or do — specific product names, services, and who their customers are
2. 2-3 SPECIFIC things that make this company unique — concrete differentiators
3. 2-3 SPECIFIC recent announcements, blog posts, product launches, funding rounds, or initiatives — cite actual events with dates
4. Their tech stack — technologies, frameworks, or technical approaches from their site, blog, or job postings
5. Company culture, mission, values, notable initiatives (DEI, open source, community involvement)
6. A two-paragraph overview demonstrating deep knowledge with 2-3 specific details

Be specific and cite concrete details. Do NOT make anything up — if you can't find info, say so.
Return your findings as a JSON object with these keys:
{COMPANY_SCHEMA_STR}"""

    try:
        result = chat_perplexity(perplexity_client, prompt, max_tokens=4096)

        text = result.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        parsed = json.loads(text.strip())

        for key in ["products_services", "key_features", "recent_news",
                    "tech_stack", "culture_values", "summary_text"]:
            if key not in parsed:
                parsed[key] = ""

        parsed.setdefault("company", company)
        parsed.setdefault("website", website)
        return parsed

    except json.JSONDecodeError:
        log.warning(f"    Could not parse Perplexity response as JSON for {company}")
        return {
            "products_services": "", "key_features": "", "recent_news": "",
            "tech_stack": "", "culture_values": "", "summary_text": text,
            "company": company, "website": website
        }
    except Exception as e:
        log.error(f"    Perplexity research failed for {company}: {e}")
        return {"company": company, "website": website}


def main():
    parser = argparse.ArgumentParser(description="Company research workflow")
    parser.add_argument("--batch", default=None, help="Batch name (default: today's date)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

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

    # Deduplicate by company
    seen = {}
    for row in rows:
        company = row.get("Company", "").strip()
        if company and company not in seen:
            seen[company] = row
    unique_rows = list(seen.values())

    log.info(f"Researching {len(unique_rows)} companies → {output_dir}")

    perplexity_client = create_perplexity_client()

    def _research_one(row):
        company = row.get("Company", "").strip()
        email = row.get("Email", "").strip()

        # If Company field is a URL, use it directly as the website
        if company.startswith("http"):
            website = company
            # Derive a display name from the domain for logging/filenames
            from urllib.parse import urlparse
            host = urlparse(website).hostname or company
            company = host.replace("www.", "").split(".")[0].capitalize()
        else:
            domain = domain_from_email(email)
            website = f"https://{domain}" if domain else ""

        out_file = output_dir / f"{filename_safe(company)}.json"
        if out_file.exists():
            log.info(f"  ⏭ {company} — research exists, skipping")
            return

        try:
            log.info(f"  Researching: {company} ({website})")
            summary = research_company(perplexity_client, company, website)
            out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            log.info(f"  ✓ Saved {out_file.name}")
        except Exception as e:
            log.error(f"  ✗ Failed for {company}: {e}")

    with ThreadPoolExecutor(max_workers=min(len(unique_rows), 3)) as pool:
        futures = [pool.submit(_research_one, row) for row in unique_rows]
        for f in as_completed(futures):
            f.result()


if __name__ == "__main__":
    main()
