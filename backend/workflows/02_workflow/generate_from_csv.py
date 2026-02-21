#!/usr/bin/env python3
"""Workflow 2: Email Template Generation — generate tailored _TEMPLATE.txt per company."""

import sys, json, argparse, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import config
from shared.logging_setup import setup as setup_logging
from shared.csv_utils import read_csv, filter_not_emailed
from shared.company_utils import normalize, filename_safe
from shared.job_types import resolve as resolve_job_type
from shared.resume_utils import get_resume_path, extract_pdf_text, find_company_resume

from anthropic import Anthropic

log = logging.getLogger("workflows")

TEMPLATE_FORMAT = """\
COMPANY: {company}
JOB TITLE: {job_title}
JOB URL: {job_url}

===== EMAIL TEMPLATE =====

SUBJECT: {subject}

BODY:
{body}

===== INSTRUCTIONS =====
1. Find the recruiter's contact information (email and name)
2. Replace [RECRUITER_FIRST_NAME] in the subject and body with their first name
3. Review and personalize if needed
4. Send when ready!
"""


def load_research(company: str, research_dir: Path | None) -> dict | None:
    """Try to load research JSON for a company."""
    if not research_dir or not research_dir.is_dir():
        return None
    safe = filename_safe(company)
    path = research_dir / f"{safe}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # Try case-insensitive match
    norm = normalize(company)
    for f in research_dir.glob("*.json"):
        if normalize(f.stem) == norm:
            return json.loads(f.read_text(encoding="utf-8"))
    return None


def generate_template(client: Anthropic, company: str, job_type_str: str,
                      research: dict | None, resume_text: str) -> dict:
    """Use Claude to generate an email template."""
    research_context = ""
    if research:
        research_context = (
            f"\nCompany research:\n"
            f"- Products/Services: {research.get('products_services', 'N/A')}\n"
            f"- Key Features: {research.get('key_features', 'N/A')}\n"
            f"- Recent News: {research.get('recent_news', 'N/A')}\n"
            f"- Summary: {research.get('summary_text', 'N/A')}\n"
        )

    resume_context = ""
    if resume_text:
        resume_context = f"\nJustin's resume content:\n{resume_text[:4000]}\n"

    prompt = (
        f"Generate a cold outreach email template for {config.CANDIDATE_NAME} to send to a recruiter at {company}.\n"
        f"Job type: {job_type_str}\n"
        f"{research_context}"
        f"{resume_context}\n"
        f"The email should:\n"
        f"- Open with 2-3 sentences about what the company is doing (show you researched them)\n"
        f"- Include 1 sentence connecting Justin's concrete results/outcomes from his resume to the company (outcomes matter, not process)\n"
        f"- End by asking about internship opportunities for summer and offering a 10-15 minute chat\n"
        f"- Use [RECRUITER_FIRST_NAME] as placeholder for the recruiter's first name\n"
        f"- Be concise, warm, and professional\n\n"
        f"Return ONLY a JSON object with these keys:\n"
        f'- "subject": the email subject line (should mention reaching out via LinkedIn)\n'
        f'- "body": the full email body\n'
        f'- "job_title": inferred job title or "N/A"\n'
    )

    resp = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return {"subject": f"Hi [RECRUITER_FIRST_NAME], reaching out about {company}", "body": text, "job_title": "N/A"}


def main():
    parser = argparse.ArgumentParser(description="Generate email templates from CSV")
    parser.add_argument("csv_path", help="Path to recruiters CSV")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--research-dir", type=Path, default=None, help="Path to research JSON directory")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing templates")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory for templates")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    output_dir = args.output_dir or config.OUTPUT_DIR / "emails"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find latest research dir if not specified
    research_dir = args.research_dir
    if not research_dir:
        # Try to find most recent research output
        if config.OUTPUT_DIR.exists():
            batches = sorted([d for d in config.OUTPUT_DIR.iterdir() if (d / "research").is_dir()])
            if batches:
                research_dir = batches[-1] / "research"
                log.info(f"Using research from: {research_dir}")

    rows = filter_not_emailed(read_csv(args.csv_path))
    if not rows:
        log.info("No contacts to process (all marked as emailed)")
        return

    # Deduplicate by company (first row per company wins)
    seen = {}
    for row in rows:
        company = row.get("Company", "").strip()
        if company and normalize(company) not in seen:
            seen[normalize(company)] = row

    log.info(f"Processing {len(seen)} unique companies")

    if args.dry_run:
        for norm, row in seen.items():
            company = row["Company"]
            job_type = resolve_job_type(row.get("Job Type", ""))
            resume = get_resume_path(company, job_type)
            research = load_research(company, research_dir)
            log.info(
                f"  [DRY RUN] {company} | type={job_type.value} | "
                f"resume={'✓' if resume else '✗'} | research={'✓' if research else '✗'}"
            )
        return

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    for norm, row in seen.items():
        company = row["Company"]
        safe_name = filename_safe(company)
        out_path = output_dir / f"{safe_name}_TEMPLATE.txt"

        if out_path.exists() and not args.overwrite:
            log.info(f"  ⏭ {company} — template exists (use --overwrite)")
            continue

        try:
            job_type = resolve_job_type(row.get("Job Type", ""))
            research = load_research(company, research_dir)
            resume_path = get_resume_path(company, job_type)
            resume_text = extract_pdf_text(resume_path) if resume_path else ""

            log.info(f"  Generating template for: {company} (type={job_type.value})")
            result = generate_template(client, company, job_type.value, research, resume_text)

            content = TEMPLATE_FORMAT.format(
                company=company,
                job_title=result.get("job_title", "N/A"),
                job_url=result.get("job_url", "N/A"),
                subject=result.get("subject", ""),
                body=result.get("body", ""),
            )
            out_path.write_text(content, encoding="utf-8")
            log.info(f"  ✓ Saved {out_path.name}")
        except Exception as e:
            log.error(f"  ✗ Failed for {company}: {e}")


if __name__ == "__main__":
    main()
