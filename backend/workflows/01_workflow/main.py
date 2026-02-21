#!/usr/bin/env python3
"""Workflow 1: Company Research — scrape websites and summarize with Claude."""

import sys, json, argparse, logging
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, filter_not_emailed
from shared.company_utils import filename_safe

from firecrawl import FirecrawlApp
from anthropic import Anthropic

log = logging.getLogger("workflows")


def domain_from_email(email: str) -> str:
    """Extract the domain from an email address."""
    return email.split("@", 1)[1] if "@" in email else ""


NEWS_KEYWORDS = ["blog", "news", "press", "announce", "update", "insight", "resource", "case-stud", "whats-new", "launch"]


def find_news_urls(firecrawl: FirecrawlApp, url: str) -> list[str]:
    """Use Firecrawl map to discover actual blog/news/press pages on the site."""
    try:
        site_map = firecrawl.map(url, limit=100)
        links = site_map.links if hasattr(site_map, "links") and site_map.links else []
        # Filter for pages that look like news/blog content
        matches = [
            link for link in links
            if any(kw in link.lower() for kw in NEWS_KEYWORDS)
        ]
        return matches[:3]  # scrape up to 3 relevant pages
    except Exception as e:
        log.warning(f"Could not map {url}: {e}")
        return []


def scrape_website(firecrawl: FirecrawlApp, url: str) -> str:
    """Use Firecrawl to scrape homepage + discover and scrape blog/news pages."""
    texts = []

    # Scrape homepage
    try:
        result = firecrawl.scrape(url, formats=["markdown"])
        homepage = result.markdown if hasattr(result, "markdown") and result.markdown else ""
        if homepage:
            texts.append(f"=== HOMEPAGE ===\n{homepage[:4000]}")
    except Exception as e:
        log.warning(f"Could not scrape homepage {url}: {e}")

    # Discover and scrape actual news/blog pages from the site
    news_urls = find_news_urls(firecrawl, url)
    for news_url in news_urls:
        try:
            result = firecrawl.scrape(news_url, formats=["markdown"])
            page = result.markdown if hasattr(result, "markdown") and result.markdown else ""
            if page:
                texts.append(f"=== {news_url} ===\n{page[:2500]}")
        except Exception:
            continue

    return "\n\n".join(texts)[:10000]


def summarize_company(client: Anthropic, company: str, website_text: str) -> dict:
    """Use Claude to summarize a company's website content."""
    specifics_instruction = (
        "IMPORTANT: For key_features and recent_news, do NOT give generic metrics or vague statements. "
        "Find something SPECIFIC and RECENT that the company has done — for example: "
        "a new product launch, a specific blog post about how they use AI agents in operations, "
        "a new team structure (like a compliance vault or audit framework), a recent partnership, "
        "a specific technical approach they blogged about, or a concrete initiative. "
        "The goal is to show the reader genuinely researched this company, not just read the tagline."
    )

    if website_text:
        user_prompt = (
            f"Here is text scraped from {company}'s website (homepage + blog/news):\n\n{website_text}\n\n"
            f"{specifics_instruction}\n\n"
            f"Return a JSON object with these keys:\n"
            f'- "products_services": what the company sells or does\n'
            f'- "key_features": something SPECIFIC about how they operate or what makes them unique — reference a concrete detail from their site\n'
            f'- "recent_news": a SPECIFIC recent announcement, blog post, product update, or initiative — cite the actual thing, not "they have been growing"\n'
            f'- "summary_text": a one-paragraph overview that includes at least one specific detail that proves you read their website'
        )
    else:
        user_prompt = (
            f"I couldn't scrape {company}'s website. Based on your general knowledge, "
            f"summarize this company.\n\n"
            f"{specifics_instruction}\n\n"
            f"Return a JSON object with these keys:\n"
            f'- "products_services": what the company sells or does\n'
            f'- "key_features": something SPECIFIC about how they operate — avoid generic statements\n'
            f'- "recent_news": any SPECIFIC recent announcements or launches you know about — if none, say "No specific recent news available"\n'
            f'- "summary_text": a one-paragraph overview'
        )

    resp = client.messages.create(
        model="claude-3-haiku-20240307",
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

    # Deduplicate by company (first row per company wins)
    seen = {}
    for row in rows:
        company = row.get("Company", "").strip()
        if company and company not in seen:
            seen[company] = row
    unique_rows = list(seen.values())

    log.info(f"Researching {len(unique_rows)} companies → {output_dir}")

    firecrawl = FirecrawlApp(api_key=config.get("FIRECRAWL_API_KEY", required=True))
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    for row in unique_rows:
        company = row.get("Company", "").strip()
        email = row.get("Email", "").strip()
        domain = domain_from_email(email)
        website = f"https://{domain}" if domain else ""

        try:
            log.info(f"Researching: {company} ({website})")
            website_text = scrape_website(firecrawl, website) if website else ""
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
